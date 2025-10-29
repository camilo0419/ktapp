from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView, TemplateView, DeleteView

from django.db.models import Q, Sum, F, Value as V, DecimalField, ExpressionWrapper
from django.db.models.functions import Coalesce, Cast

from .models import Cliente, Transaccion, Abono
from .forms import ClienteForm, TransaccionForm, AbonoForm, TransaccionItemFormSet
from .analytics import track
from django.utils import timezone
from datetime import date, timedelta
from collections import defaultdict
from calendar import monthrange
from datetime import datetime
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.conf import settings
import os
import sys
from urllib.parse import urlparse
from io import BytesIO
from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string






# ========= CLIENTES =========

class ClienteListView(LoginRequiredMixin, ListView):
    model = Cliente
    template_name = "cartera/clientes_list.html"
    context_object_name = "object_list"
    paginate_by = 10

    def get_queryset(self):
        q = (self.request.GET.get("q") or "").strip()
        qs = Cliente.objects.all()
        if q:
            qs = qs.filter(
                Q(nombre__icontains=q) |
                Q(telefono__icontains=q) |
                Q(correo__icontains=q)
            )
        return qs.order_by("nombre")

    def get(self, request, *args, **kwargs):
        resp = super().get(request, *args, **kwargs)
        track(
            request,
            nombre="clientes_list",
            categoria="view",
            etiqueta=f"page={self.request.GET.get('page','1')}",
            extras={"q": self.request.GET.get("q", "")},
        )
        return resp


class ClienteCreateView(LoginRequiredMixin, CreateView):
    model = Cliente
    form_class = ClienteForm
    template_name = "cartera/cliente_form.html"
    success_url = reverse_lazy("cartera:clientes_list")

    def form_valid(self, form):
        resp = super().form_valid(form)
        track(self.request, "cliente_create", "action",
              etiqueta=f"cliente_id={self.object.id}",
              extras={"nombre": self.object.nombre})
        messages.success(self.request, "Cliente creado correctamente.")
        return resp


class ClienteUpdateView(LoginRequiredMixin, UpdateView):
    model = Cliente
    form_class = ClienteForm
    template_name = "cartera/cliente_form.html"
    success_url = reverse_lazy("cartera:clientes_list")

    def form_valid(self, form):
        resp = super().form_valid(form)
        track(self.request, "cliente_update", "action",
              etiqueta=f"cliente_id={self.object.id}",
              extras={"activo": self.object.activo})
        messages.success(self.request, "Cliente actualizado.")
        return resp


class ClienteDetailView(LoginRequiredMixin, DetailView):
    model = Cliente
    template_name = "cartera/cliente_detail.html"
    context_object_name = "obj"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        obj: Cliente = self.object

        tx = (
            obj.transacciones
            .select_related("cliente")
            .prefetch_related("abonos", "items")
            .order_by("-creado")
        )
        ctx["tx_list"] = tx

        dec = DecimalField(max_digits=14, decimal_places=2)
        zero = V(Decimal("0.00"), output_field=dec)

        base_expr = ExpressionWrapper(
            F("items__precio_unitario") * F("items__cantidad"),
            output_field=dec,
        )
        desc_pct = Cast(F("items__descuento"), output_field=dec)
        desc_num_expr = ExpressionWrapper(base_expr * desc_pct, output_field=dec)

        base_pag = tx.filter(pagado=True).aggregate(
            s=Coalesce(Sum(base_expr, output_field=dec), zero)
        )["s"] or Decimal("0.00")

        desc_num_pag = tx.filter(pagado=True).aggregate(
            s=Coalesce(Sum(desc_num_expr, output_field=dec), zero)
        )["s"] or Decimal("0.00")

        ctx["total_pagado"] = base_pag - (desc_num_pag / Decimal("100.00"))

        pendiente_total = Decimal("0.00")
        for t in tx:
            if not t.pagado:
                pendiente_total += Decimal(str(t.saldo_actual))
        ctx["total_pendiente"] = pendiente_total
        ctx["tx_count"] = tx.count()
        return ctx

    def get(self, request, *args, **kwargs):
        resp = super().get(request, *args, **kwargs)
        obj: Cliente = self.object
        track(
            request,
            "cliente_detail",
            "view",
            etiqueta=f"cliente_id={obj.id}",
            extras={
                "saldo_pend": getattr(obj, "saldo_pendiente", 0),
                "tx_total": obj.transacciones.count(),
            },
        )
        return resp



def _formset_marca_vacias_como_delete(post_data, prefix):
    """
    Devuelve una copia de post_data donde las filas completamente vacías
    del formset <prefix> quedan marcadas como DELETE=on.
    """
    data = post_data.copy()
    total = int(data.get(f"{prefix}-TOTAL_FORMS", "0") or 0)
    campos = ("producto", "precio_unitario", "cantidad", "descuento")

    for i in range(total):
        # si ya viene marcada para borrar, seguimos
        if data.get(f"{prefix}-{i}-DELETE"):
            continue

        # revisar si TODOS los campos están vacíos
        vacia = True
        for name in campos:
            raw = (data.get(f"{prefix}-{i}-{name}") or "").strip()
            if raw != "":
                vacia = False
                break

        if vacia:
            data[f"{prefix}-{i}-DELETE"] = "on"

    return data


TIPO_MAP   = {"natura": "NAT", "accesorios": "ACC", "otros": "OTR"}
TIPO_LABEL = {"NAT": "Natura", "ACC": "Accesorios", "OTR": "Otros"}

def _parse_tipos(request):
    raw_list = request.GET.getlist("tipos")
    if len(raw_list) == 1 and "," in raw_list[0]:
        raw_list = [x.strip() for x in raw_list[0].split(",") if x.strip()]
    codes = []
    for r in raw_list:
        code = TIPO_MAP.get(r.lower())
        if code and code not in codes:
            codes.append(code)
    return codes or None

# utils/pdf.py
import os
from django.conf import settings
from django.contrib.staticfiles import finders

def link_callback(uri, rel):
    """
    Convierte URIs de /static/ y /media/ a rutas absolutas en disco.
    Sirve tanto en local (sin collectstatic) como en producción.
    """
    # STATIC
    if uri.startswith(settings.STATIC_URL):
        rel_path = uri.replace(settings.STATIC_URL, "")
        if settings.STATIC_ROOT:
            path = os.path.join(settings.STATIC_ROOT, rel_path)
            if os.path.isfile(path):
                return path
        found = finders.find(rel_path)
        if found:
            return found
        if os.path.isfile(uri):
            return uri
        raise FileNotFoundError(f"[xhtml2pdf] STATIC no encontrado: {uri}")

    # MEDIA
    if getattr(settings, "MEDIA_URL", None) and uri.startswith(settings.MEDIA_URL):
        rel_path = uri.replace(settings.MEDIA_URL, "")
        if settings.MEMEDIA_ROOT:
            path = os.path.join(settings.MEDIA_ROOT, rel_path)
            if os.path.isfile(path):
                return path
        if os.path.isfile(uri):
            return uri
        raise FileNotFoundError(f"[xhtml2pdf] MEDIA no encontrado: {uri}")

    # Rutas absolutas locales o file://
    if uri.startswith("file://"):
        local_path = uri[7:]
        if os.path.isfile(local_path):
            return local_path
    if os.path.isabs(uri) and os.path.isfile(uri):
        return uri

    return uri


def _pick_engine():
    """
    Elige motor según settings/entorno:
    - weasyprint en producción (o si se fuerza),
    - xhtml2pdf en local/Windows por rapidez.
    """
    forced = getattr(settings, "PDF_ENGINE", "auto").lower()
    if forced in ("weasyprint", "xhtml2pdf"):
        return forced

    # AUTO: si es Windows o DEBUG => xhtml2pdf; si no => weasyprint
    if sys.platform.startswith("win") or settings.DEBUG:
        return "xhtml2pdf"
    return "weasyprint"

@login_required
def estado_cuenta(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    tipos_codes = _parse_tipos(request)
    hoy = timezone.localdate()

    if not request.GET.get("ready"):
        return render(request, "cartera/estado_cuenta_select.html", {
            "cliente": cliente, "hoy": hoy, "tipos_sel": set(tipos_codes or []),
        })

    qs = (cliente.transacciones
          .filter(pagado=False)
          .select_related("cliente")
          .prefetch_related("items", "abonos")
          .order_by("-fecha"))
    if tipos_codes:
        qs = qs.filter(tipo__in=tipos_codes)

    codes_order = tipos_codes or ["NAT", "ACC", "OTR"]

    grouped = {code: [] for code in codes_order}

    def zero():
        return {"base": Decimal("0"), "desc": Decimal("0"),
                "abonado": Decimal("0"), "saldo": Decimal("0")}

    subtotals = {code: zero() for code in codes_order}
    totals    = zero()

    for tx in qs:
        base_total = Decimal("0")
        desc_total = Decimal("0")
        for it in tx.items.all():
            base = Decimal(it.precio_unitario or 0) * Decimal(it.cantidad or 0)
            pct  = Decimal(it.descuento or 0) / Decimal("100")
            base_total += base
            desc_total += (base * pct)

        # dejar a mano para el template
        tx.base_total = base_total
        tx.desc_total = desc_total

        if tx.tipo in grouped:
            grouped[tx.tipo].append(tx)

        abonado = Decimal(str(tx.total_abonos or 0))
        saldo   = Decimal(str(tx.saldo_actual or 0))

        if tx.tipo in subtotals:
            subtotals[tx.tipo]["base"]    += base_total
            subtotals[tx.tipo]["desc"]    += desc_total
            subtotals[tx.tipo]["abonado"] += abonado
            subtotals[tx.tipo]["saldo"]   += saldo

        totals["base"]    += base_total
        totals["desc"]    += desc_total
        totals["abonado"] += abonado
        totals["saldo"]   += saldo

    tipos_human = [TIPO_LABEL[c] for c in codes_order]

    include_acc    = (tipos_codes is None) or ("ACC" in (tipos_codes or []))
    include_nonacc = (tipos_codes is None) or any(c in (tipos_codes or []) for c in ("NAT","OTR"))
    show_liliana   = include_acc
    show_kathe     = include_nonacc

    grouped_list = []
    for code in codes_order:
        grouped_list.append({
            "code": code,
            "label": TIPO_LABEL[code],
            "txs": grouped[code],
            "subtotal": subtotals[code],
        })

    return render(request, "cartera/estado_cuenta.html", {
        "cliente": cliente,
        "hoy": hoy,
        "grouped": grouped_list,
        "totals": totals,
        "tipos_human": tipos_human,
        "show_liliana": show_liliana,
        "show_kathe": show_kathe,
    })

def _build_estado_ctx(request, cliente, tipos_codes):
    """
    Reutiliza el mismo cómputo de estado_cuenta (pendientes),
    devolviendo el contexto listo para el template HTML o PDF.
    """
    from decimal import Decimal
    from django.utils import timezone

    hoy = timezone.localdate()
    qs = (cliente.transacciones
          .filter(pagado=False)
          .select_related("cliente")
          .prefetch_related("items", "abonos")
          .order_by("-fecha"))

    if tipos_codes:
        qs = qs.filter(tipo__in=tipos_codes)

    codes_order = tipos_codes or ["NAT", "ACC", "OTR"]

    grouped = {code: [] for code in codes_order}

    def zero():
        return {"base": Decimal("0"), "desc": Decimal("0"),
                "abonado": Decimal("0"), "saldo": Decimal("0")}

    subtotals = {code: zero() for code in codes_order}
    totals    = zero()

    for tx in qs:
        base_total = Decimal("0")
        desc_total = Decimal("0")
        for it in tx.items.all():
            base = Decimal(it.precio_unitario or 0) * Decimal(it.cantidad or 0)
            pct  = Decimal(it.descuento or 0) / Decimal("100")
            base_total += base
            desc_total += (base * pct)

        tx.base_total = base_total
        tx.desc_total = desc_total

        if tx.tipo in grouped:
            grouped[tx.tipo].append(tx)

        abonado = Decimal(str(tx.total_abonos or 0))
        saldo   = Decimal(str(tx.saldo_actual or 0))

        if tx.tipo in subtotals:
            subtotals[tx.tipo]["base"]    += base_total
            subtotals[tx.tipo]["desc"]    += desc_total
            subtotals[tx.tipo]["abonado"] += abonado
            subtotals[tx.tipo]["saldo"]   += saldo

        totals["base"]    += base_total
        totals["desc"]    += desc_total
        totals["abonado"] += abonado
        totals["saldo"]   += saldo

    tipos_human = [TIPO_LABEL[c] for c in codes_order]

    include_acc    = (tipos_codes is None) or ("ACC" in (tipos_codes or []))
    include_nonacc = (tipos_codes is None) or any(c in (tipos_codes or []) for c in ("NAT","OTR"))
    show_liliana   = include_acc
    show_kathe     = include_nonacc

    grouped_list = []
    for code in codes_order:
        grouped_list.append({
            "code": code,
            "label": TIPO_LABEL[code],
            "txs": grouped[code],
            "subtotal": subtotals[code],
        })

    return {
        "cliente": cliente,
        "hoy": hoy,
        "grouped": grouped_list,
        "totals": totals,
        "tipos_human": tipos_human,
        "show_liliana": show_liliana,
        "show_kathe": show_kathe,
    }

from utils.pdf import link_callback  # NUEVO import
from xhtml2pdf import pisa

def _sanitize_filename_part(s: str) -> str:
    safe = s.replace(" ", "_")
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in safe).strip("_")


def _weasy_url_fetcher(url):
    """
    Fetcher para WeasyPrint que convierte URLs absolutas o paths de /static y /media
    a archivos locales en disco (evita HTTP en PA free).
    """
    from urllib.parse import urlsplit
    from weasyprint import default_url_fetcher
    from django.conf import settings
    import os

    # Normaliza: si viene https://... extrae el path (/static/... o /media/...)
    try:
        parts = urlsplit(url)
        path = parts.path or url  # si no es URL, deja tal cual
    except Exception:
        path = url

    static_url = getattr(settings, "STATIC_URL", "/static/")
    media_url = getattr(settings, "MEDIA_URL", "/media/")

    # STATIC
    if path.startswith(static_url):
        rel = path.replace(static_url, "", 1)
        # 1) STATIC_ROOT (prod)
        if settings.STATIC_ROOT:
            fs_path = os.path.join(settings.STATIC_ROOT, rel)
            if os.path.isfile(fs_path):
                return {"file_obj": open(fs_path, "rb")}
        # 2) Fallback: usa el mismo resolver que xhtml2pdf
        try:
            from utils.pdf import link_callback
            fs_path = link_callback(path, None)
            if os.path.isfile(fs_path):
                return {"file_obj": open(fs_path, "rb")}
        except Exception:
            pass

    # MEDIA
    if media_url and path.startswith(media_url):
        rel = path.replace(media_url, "", 1)
        if getattr(settings, "MEDIA_ROOT", None):
            fs_path = os.path.join(settings.MEDIA_ROOT, rel)
            if os.path.isfile(fs_path):
                return {"file_obj": open(fs_path, "rb")}

    # file://
    if url.startswith("file://"):
        local = url[7:]
        if os.path.isfile(local):
            return {"file_obj": open(local, "rb")}

    # data:… o cualquier otro recurso
    return default_url_fetcher(url)


@login_required
def estado_cuenta_pdf(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    tipos_codes = _parse_tipos(request)
    ctx = _build_estado_ctx(request, cliente, tipos_codes)

    html_string = render_to_string("cartera/estado_cuenta_pdf.html", ctx, request=request)

    # Sufijo para nombre del archivo
    tipos_human = ctx.get("tipos_human", []) or []
    tipo_sufijo = "-".join(tipos_human) if tipos_human else "Todos"

    safe_name = _sanitize_filename_part(cliente.nombre)
    safe_tipo = _sanitize_filename_part(tipo_sufijo)
    filename = f"Estado_de_Cuenta_{safe_name}_{safe_tipo}.pdf"

    # ====== Intento A: WeasyPrint (con fetcher local) ======
    # Aunque _pick_engine() te diga 'weasyprint', aquí lo forzamos a usar fetcher
    # para evitar HTTP. Si algo falla, caemos a xhtml2pdf.
    try:
        from weasyprint import HTML, CSS
        # base_url puede ser el sitio; pero como tenemos fetcher que resuelve a disco,
        # no dependemos de HTTP.
        base_url = request.build_absolute_uri("/")
        pdf_bytes = HTML(
            string=html_string,
            base_url=request.build_absolute_uri("/"),
            url_fetcher=_weasy_url_fetcher,   # <- CLAVE
        ).write_pdf(
            stylesheets=[
                CSS(string="""
                    @page { size: A4; margin: 18mm; }
                    * { -weasy-hyphens: auto; }
                """)
            ]
        )
        resp = HttpResponse(pdf_bytes, content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="{filename}"'
        return resp
    except Exception:
        pass  # cae a xhtml2pdf

    # ====== Intento B: xhtml2pdf (con link_callback) ======
    pdf_io = BytesIO()
    pisa_status = pisa.CreatePDF(
        src=html_string,
        dest=pdf_io,
        encoding="utf-8",
        link_callback=link_callback,  # resuelve STATIC/MEDIA a disco
    )
    if pisa_status.err:
        raise Http404("No se pudo generar el PDF.")

    resp = HttpResponse(pdf_io.getvalue(), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp

# ========= helpers para formset =========

def _marcar_filas_vacias(formset):
    """
    Marca como 'empty_permitted' los formularios completamente vacíos,
    para que no generen errores de 'campo obligatorio'.
    Devuelve cuántas filas NO vacías hay (las que sí deben guardarse).
    """
    no_vacias = 0
    campos = ("producto", "precio_unitario", "cantidad", "descuento")
    for f in formset.forms:
        # obtener valores crudos del POST (antes de clean)
        vacia = True
        for name in campos:
            field_name = f"{f.prefix}-{name}"
            raw = formset.data.get(field_name, "").strip()
            if raw not in ("", None):
                vacia = False
                break
        if vacia:
            f.empty_permitted = True
        else:
            no_vacias += 1
    return no_vacias


# ========= TRANSACCIONES =========

class TransaccionCreateView(LoginRequiredMixin, CreateView):
    model = Transaccion
    form_class = TransaccionForm
    template_name = "cartera/tx_form.html"

    def get_initial(self):
        ini = super().get_initial()
        # Precargar cliente si viene en querystring
        cliente_id = self.request.GET.get("cliente")
        if cliente_id:
            ini["cliente"] = cliente_id
        # Precargar HOY en formato ISO (YYYY-MM-DD) para <input type="date">
        if "fecha" not in ini or not ini["fecha"]:
            ini["fecha"] = timezone.localdate().isoformat()
        return ini

    def get_success_url(self):
        return reverse_lazy("cartera:clientes_detail", args=[self.object.cliente_id])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.POST:
            ctx["formset"] = TransaccionItemFormSet(self.request.POST)
        else:
            ctx["formset"] = TransaccionItemFormSet()
        return ctx

    def post(self, request, *args, **kwargs):
        self.object = None
        form = self.get_form()

        # Validar formset con los datos del POST
        formset = TransaccionItemFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            return self.forms_valid(form, formset)
        return self.forms_invalid(form, formset)

    def forms_valid(self, form, formset):
        self.object = form.save()
        formset.instance = self.object
        formset.save()
        track(
            self.request, "tx_create", "action",
            etiqueta=f"cliente_id={self.object.cliente_id}",
            extras={
                "tipo": getattr(self.object, "tipo", ""),
                "valor": float(getattr(self.object, "valor_a_pagar", 0.0)),
                "pagado": bool(self.object.pagado),
            },
        )
        messages.success(self.request, "Transacción creada.")
        return redirect(self.get_success_url())

    def forms_invalid(self, form, formset):
        messages.error(self.request, "Revisa los campos.")
        return render(self.request, self.template_name, {"form": form, "formset": formset})

class TransaccionUpdateView(LoginRequiredMixin, UpdateView):
    model = Transaccion
    form_class = TransaccionForm
    template_name = "cartera/tx_form.html"

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        if not form.is_bound and form.instance and form.instance.pk and form.instance.fecha:
            form.fields["fecha"].initial = form.instance.fecha.strftime("%Y-%m-%d")
        return form

    def dispatch(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj.pagado:
            messages.warning(request, "Esta transacción ya está pagada y no puede editarse.")
            return redirect("cartera:clientes_detail", pk=obj.cliente_id)
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse_lazy("cartera:clientes_detail", args=[self.object.cliente_id])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if self.request.POST:
            ctx["formset"] = TransaccionItemFormSet(self.request.POST, instance=self.object)
        else:
            ctx["formset"] = TransaccionItemFormSet(instance=self.object)
        return ctx

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = self.get_form()

        data = _formset_marca_vacias_como_delete(request.POST, prefix="transaccionitem_set")
        formset = TransaccionItemFormSet(data, instance=self.object)

        if form.is_valid() and formset.is_valid():
            return self.forms_valid(form, formset)
        return self.forms_invalid(form, formset)


    def forms_valid(self, form, formset):
        self.object = form.save()
        formset.instance = self.object
        formset.save()
        track(
            self.request, "tx_update", "action",
            etiqueta=f"tx_id={self.object.id}",
            extras={
                "tipo": getattr(self.object, "tipo", ""),
                "valor": float(getattr(self.object, "valor_a_pagar", 0.0)),
                "pagado": bool(self.object.pagado),
            },
        )
        messages.success(self.request, "Transacción actualizada.")
        return redirect(self.get_success_url())

    def forms_invalid(self, form, formset):
        messages.error(self.request, "Revisa los campos.")
        return render(self.request, self.template_name, {"form": form, "formset": formset, "object": self.object})


@login_required
def transaccion_marcar_pagado(request, pk):
    tx = get_object_or_404(Transaccion, pk=pk)

    # Marcar como pagada y dejar que el save() del modelo ponga pagado_en
    if not tx.pagado:
        tx.pagado = True
        tx.save(update_fields=["pagado", "pagado_en"])
    else:
        # Si ya estaba pagada, asegúrate de que tenga timestamp
        tx.save(update_fields=["pagado", "pagado_en"])

    track(
        request, "tx_pagada", "action",
        etiqueta=f"tx_id={tx.id}",
        extras={"cliente_id": tx.cliente_id, "valor": float(getattr(tx, "valor_a_pagar", 0.0))},
    )
    messages.success(request, "Transacción marcada como pagada.")
    return redirect("cartera:clientes_detail", pk=tx.cliente_id)



# ========= ABONOS =========

class AbonoCreateView(LoginRequiredMixin, CreateView):
    model = Abono
    form_class = AbonoForm
    template_name = "cartera/abono_form.html"

    def dispatch(self, request, *args, **kwargs):
        self.tx = get_object_or_404(Transaccion, pk=kwargs["tx_id"])
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        ini = super().get_initial()
        ini.setdefault("fecha", timezone.localdate())
        ini.setdefault("hora", timezone.localtime().time().replace(microsecond=0))
        return ini

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["transaccion"] = self.tx
        return kwargs

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Vincular FK antes de validar/guardar
        form.instance.transaccion = self.tx

        # ⬅️ Fuerza el valor visible del <input type="date"> en GET
        if not form.is_bound:
            form.fields["fecha"].initial = timezone.localdate().isoformat()  # YYYY-MM-DD
            # (opcional) si quieres fijar también la hora visible:
            # form.fields["hora"].initial = timezone.localtime().time().strftime("%H:%M")

        return form

    def form_valid(self, form):
        resp = super().form_valid(form)
        track(
            self.request, "abono_create", "action",
            etiqueta=f"tx_id={self.tx.id}",
            extras={"valor": float(self.object.valor), "saldo_post": float(getattr(self.tx, "saldo_actual", 0.0))},
        )
        messages.success(self.request, "Abono registrado.")
        return resp

    def get_success_url(self):
        return reverse_lazy("cartera:clientes_detail", args=[self.tx.cliente_id])



@login_required
def abono_delete(request, pk):
    abono = get_object_or_404(Abono, pk=pk)
    cliente_id = abono.transaccion.cliente_id
    tx_id = abono.transaccion_id
    valor = float(abono.valor)
    abono.delete()
    track(
        request, "abono_delete", "action",
        etiqueta=f"tx_id={tx_id}",
        extras={"valor": valor},
    )
    messages.success(request, "Abono eliminado.")
    return redirect("cartera:clientes_detail", pk=cliente_id)


# ========= DASHBOARD =========




def _month_bounds(ref: date):
    start = ref.replace(day=1)
    last_day = monthrange(ref.year, ref.month)[1]
    end = ref.replace(day=last_day)
    return start, end


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "cartera/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        # ----- Filtros -----
        cli_id = self.request.GET.get("cliente")
        tipo   = (self.request.GET.get("tipo") or "").strip()
        mes    = (self.request.GET.get("mes") or "").strip()
        desde  = (self.request.GET.get("desde") or "").strip()
        hasta  = (self.request.GET.get("hasta") or "").strip()

        today = timezone.localdate()
        d1, d2 = _month_bounds(today)
        if mes == "prev":
            prev_end = d1 - timezone.timedelta(days=1)
            d1, d2 = _month_bounds(prev_end)
        elif mes == "year":
            d1 = today.replace(month=1, day=1)
            d2 = today.replace(month=12, day=31)

        fmt = "%Y-%m-%d"
        try:
            if desde: d1 = datetime.strptime(desde, fmt).date()
            if hasta: d2 = datetime.strptime(hasta, fmt).date()
        except Exception:
            pass

        # ----- Query base -----
        qs_all = Transaccion.objects.select_related("cliente").prefetch_related("items", "abonos")

        # Filtros comunes
        if cli_id and cli_id.isdigit():
            qs_all = qs_all.filter(cliente_id=int(cli_id))
        if tipo:
            # Mapeo de valores mostrados → códigos en base de datos
            tipo_map = {
                "natura": "NAT",
                "accesorios": "ACC",
                "otros": "OTR",
            }
            code = tipo_map.get(tipo.lower(), tipo)
            qs_all = qs_all.filter(tipo__iexact=code)


        # ----- PENDIENTES -----
        qs_pend = qs_all.filter(pagado=False)

        total_pendiente = Decimal("0")
        facturas_pendientes = 0
        por_cliente = defaultdict(Decimal)

        for t in qs_pend:
            s = Decimal(t.saldo_actual or 0)
            if s > 0:
                facturas_pendientes += 1
                total_pendiente += s
                por_cliente[t.cliente_id] += s

        # Top cliente con más cartera
        cliente_mas_cartera_nombre = ""
        cliente_mas_cartera_total = Decimal("0")
        if por_cliente:
            cid_top = max(por_cliente, key=por_cliente.get)
            cli_top = Cliente.objects.filter(id=cid_top).first()
            if cli_top:
                cliente_mas_cartera_nombre = cli_top.nombre
                cliente_mas_cartera_total = por_cliente[cid_top]

        # ----- PERÍODO -----
        qs_periodo = qs_all.filter(fecha__range=(d1, d2))

        ventas_periodo = Decimal("0")
        tx_count_periodo = qs_periodo.count()
        ventas_por_cli = defaultdict(Decimal)

        for t in qs_periodo:
            subtotal = Decimal("0")
            for it in t.items.all():
                base = Decimal(it.precio_unitario) * Decimal(it.cantidad)
                desc = Decimal(it.descuento or 0) / Decimal("100")
                subtotal += base * (Decimal("1") - desc)
            ventas_periodo += subtotal
            ventas_por_cli[t.cliente_id] += subtotal

        # Mejor cliente (mayor venta)
        mejor_cliente_nombre = ""
        mejor_cliente_total = Decimal("0")
        if ventas_por_cli:
            cid_best = max(ventas_por_cli, key=ventas_por_cli.get)
            cli_best = Cliente.objects.filter(id=cid_best).first()
            if cli_best:
                mejor_cliente_nombre = cli_best.nombre
                mejor_cliente_total = ventas_por_cli[cid_best]

        # ----- Tabla resumen pendientes (>0) -----
        resumen_por_cliente = []
        for cid, val in por_cliente.items():
            if val > 0:
                cli = Cliente.objects.filter(id=cid).first()
                if cli:
                    resumen_por_cliente.append({
                        "id": cid,
                        "nombre": cli.nombre,
                        "pendiente": val,
                    })
        resumen_por_cliente.sort(key=lambda x: x["pendiente"], reverse=True)

        # ----- Contexto -----
        ctx.update({
            # Filtros actuales
            "f_cli": cli_id or "",
            "f_tipo": tipo or "",
            "f_mes": mes or "act",
            "f_desde": d1,
            "f_hasta": d2,

            # Listas para selects
            "clientes_for_select": Cliente.objects.order_by("nombre").values("id", "nombre"),
            "tipos_for_select": ["Natura", "Accesorios", "Otros"],

            # KPIs
            "valor_pendiente": total_pendiente,
            "facturas_pendientes": facturas_pendientes,
            "cliente_mas_cartera_nombre": cliente_mas_cartera_nombre,
            "cliente_mas_cartera_total": cliente_mas_cartera_total,
            "ventas_periodo": ventas_periodo,
            "tx_periodo": tx_count_periodo,
            "mejor_cliente_nombre": mejor_cliente_nombre,
            "mejor_cliente_total": mejor_cliente_total,

            # Tabla
            "resumen_por_cliente": resumen_por_cliente,
        })
        return ctx



class TransaccionDetailView(LoginRequiredMixin, DetailView):
    model = Transaccion
    template_name = "cartera/tx_detail.html"
    context_object_name = "tx"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        tx = self.object
        ctx["items"] = tx.items.all()
        ctx["abonos"] = tx.abonos.all()
        return ctx

class AbonoUpdateView(LoginRequiredMixin, UpdateView):
    model = Abono
    form_class = AbonoForm
    template_name = "cartera/abono_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # Pasamos la transacción a la que pertenece (por validación)
        kwargs["transaccion"] = self.object.transaccion
        return kwargs

    def get_success_url(self):
        return reverse_lazy("cartera:clientes_detail", args=[self.object.transaccion.cliente_id])


class TransaccionDeleteView(LoginRequiredMixin, DeleteView):
    model = Transaccion
    # si tuvieras un template de confirmación, indícalo aquí:
    template_name = "cartera/tx_confirm_delete.html"

    def dispatch(self, request, *args, **kwargs):
        # cacheamos el cliente para usarlo en get_success_url
        self.object = self.get_object()
        self._cliente_id = self.object.cliente_id
        return super().dispatch(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        # mensaje antes de borrar
        messages.success(request, "Transacción eliminada.")
        return super().delete(request, *args, **kwargs)

    def get_success_url(self):
        # redirigir al detalle del cliente después del delete
        return reverse_lazy("cartera:clientes_detail", args=[self._cliente_id])



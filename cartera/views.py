from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView, TemplateView

from django.db.models import Q, Sum, F, Value as V, DecimalField, ExpressionWrapper
from django.db.models.functions import Coalesce, Cast


from .models import Cliente, Transaccion, Abono
from .forms import ClienteForm, TransaccionForm, AbonoForm, TransaccionItemFormSet
from .analytics import track
from django.utils import timezone
from datetime import date, timedelta



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

# views.py (solo la clase)
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q, Sum, F, Value as V, DecimalField, ExpressionWrapper
from django.db.models.functions import Coalesce, Cast
from django.utils import timezone
from django.views.generic import TemplateView

from .models import Cliente, Transaccion
from calendar import monthrange

def _month_bounds(ref: date):
    """Inicio y fin (inclusive) del mes de 'ref'."""
    start = ref.replace(day=1)
    last_day = monthrange(ref.year, ref.month)[1]
    end = ref.replace(day=last_day)
    return start, end


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "cartera/dashboard.html"

    # ---------- Helpers de fechas ----------
    def _resolve_period(self, GET):
        """
        Devuelve (d1, d2, mes_code) donde d1/d2 son fechas (date) inclusive.
        mes: act | prev | year | custom
        """
        today = timezone.localdate()

        mes = (GET.get("mes") or "act").strip()
        raw_d1 = (GET.get("desde") or "").strip()
        raw_d2 = (GET.get("hasta") or "").strip()

        if mes in ("act", "prev", "year"):
            if mes == "act":
                d1, d2 = _month_bounds(today)
            elif mes == "prev":
                prev_month = (today.replace(day=1) - timedelta(days=1))
                d1, d2 = _month_bounds(prev_month)
            else:  # year
                d1 = date(today.year, 1, 1)
                d2 = date(today.year, 12, 31)
        else:
            # custom / cuando vengan fechas manuales
            try:
                d1 = date.fromisoformat(raw_d1)
            except Exception:
                d1 = today.replace(day=1)
            try:
                d2 = date.fromisoformat(raw_d2)
            except Exception:
                d2 = _month_bounds(today)[1]
            mes = "custom"

        # Normaliza: si usuario puso desde>hasta, corrige
        if d1 > d2:
            d1, d2 = d2, d1
        return d1, d2, mes

    # ---------- Vista ----------
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        # --- Filtros GET ---
        cliente_id = (self.request.GET.get("cliente") or "").strip()
        d1, d2, mes_code = self._resolve_period(self.request.GET)

        # --- Campos y expresiones comunes ---
        dec = DecimalField(max_digits=14, decimal_places=2)
        zero = V(Decimal("0.00"), output_field=dec)

        # Sobre Transaccion.items
        base_it_tx = ExpressionWrapper(
            F("items__precio_unitario") * F("items__cantidad"),
            output_field=dec,
        )
        descpct_it_tx = Cast(F("items__descuento"), output_field=dec)  # 10|20|30 o None
        descnum_it_tx = ExpressionWrapper(base_it_tx * descpct_it_tx, output_field=dec)

        # Sobre Cliente -> transacciones__items
        base_it_cli = ExpressionWrapper(
            F("transacciones__items__precio_unitario") * F("transacciones__items__cantidad"),
            output_field=dec,
        )
        descpct_it_cli = Cast(F("transacciones__items__descuento"), output_field=dec)
        descnum_it_cli = ExpressionWrapper(base_it_cli * descpct_it_cli, output_field=dec)

        # Filtros de cliente
        q_cli_tx = Q()
        q_cli_cli = Q()
        if cliente_id.isdigit():
            q_cli_tx &= Q(cliente_id=int(cliente_id))
            q_cli_cli &= Q(id=int(cliente_id))

        # ---------------- KPIs sin filtro de fecha ----------------
        # Valor pendiente (saldo vivo) y Facturas pendientes
        pend_base = Transaccion.objects.filter(q_cli_tx).aggregate(
            s=Coalesce(Sum(base_it_tx, filter=Q(pagado=False), output_field=dec), zero)
        )["s"] or Decimal("0")
        pend_descnum = Transaccion.objects.filter(q_cli_tx).aggregate(
            s=Coalesce(Sum(descnum_it_tx, filter=Q(pagado=False), output_field=dec), zero)
        )["s"] or Decimal("0")
        pend_abonos = Transaccion.objects.filter(q_cli_tx).aggregate(
            s=Coalesce(Sum("abonos__valor", filter=Q(pagado=False), output_field=dec), zero)
        )["s"] or Decimal("0")
        valor_pendiente = pend_base - (pend_descnum / Decimal("100")) - pend_abonos

        facturas_pendientes = Transaccion.objects.filter(q_cli_tx, pagado=False).distinct().count()

        # ---------------- KPIs con filtro de fecha ----------------
        tx_period_qs = (
            Transaccion.objects
            .filter(q_cli_tx, fecha__gte=d1, fecha__lte=d2)
            .distinct()
        )
        base_per = tx_period_qs.aggregate(
            s=Coalesce(Sum(base_it_tx, output_field=dec), zero)
        )["s"] or Decimal("0")
        descnum_per = tx_period_qs.aggregate(
            s=Coalesce(Sum(descnum_it_tx, output_field=dec), zero)
        )["s"] or Decimal("0")
        ventas_periodo = base_per - (descnum_per / Decimal("100"))
        tx_periodo = tx_period_qs.count()

        # Mejor cliente en el período (sumando ventas dentro del rango y cliente=Todos)
        mejor_cliente_nombre = "Sin datos en el período."
        mejor_cliente_total = Decimal("0")
        mejor_qs = (
            Cliente.objects
            .annotate(
                tot_base=Coalesce(Sum(
                    base_it_cli,
                    filter=Q(transacciones__fecha__gte=d1, transacciones__fecha__lte=d2),
                    output_field=dec
                ), zero),
                tot_desc=Coalesce(Sum(
                    descnum_it_cli,
                    filter=Q(transacciones__fecha__gte=d1, transacciones__fecha__lte=d2),
                    output_field=dec
                ), zero),
            )
            .annotate(tot_per=ExpressionWrapper(F("tot_base") - (F("tot_desc") / Decimal("100")), output_field=dec))
            .order_by("-tot_per")
            .values("nombre", "tot_per")
        )
        if mejor_qs:
            top = next((r for r in mejor_qs if (r["tot_per"] or Decimal("0")) > 0), None)
            if top:
                mejor_cliente_nombre = top["nombre"]
                mejor_cliente_total = top["tot_per"] or Decimal("0")

        # Cliente con más cartera (sin filtro de fecha)
        cartera_qs = (
            Cliente.objects.filter(q_cli_cli)
            .annotate(
                pend_base=Coalesce(Sum(base_it_cli, filter=Q(transacciones__pagado=False), output_field=dec), zero),
                pend_desc=Coalesce(Sum(descnum_it_cli, filter=Q(transacciones__pagado=False), output_field=dec), zero),
                pend_abn=Coalesce(Sum("transacciones__abonos__valor", filter=Q(transacciones__pagado=False), output_field=dec), zero),
            )
            .annotate(pend=ExpressionWrapper(F("pend_base") - (F("pend_desc") / Decimal("100")) - F("pend_abn"), output_field=dec))
            .order_by("-pend")
            .values("nombre", "pend")
        )
        if cartera_qs:
            topc = cartera_qs[0]
            cliente_mas_cartera_nombre = topc["nombre"]
            cliente_mas_cartera_total = topc["pend"] or Decimal("0")
        else:
            cliente_mas_cartera_nombre = "Sin pendientes."
            cliente_mas_cartera_total = Decimal("0")

        # Tabla: Pendiente total por cliente (filtra por cliente si se selecciona)
        resumen_qs = (
            Cliente.objects.filter(q_cli_cli)
            .annotate(
                pend_base=Coalesce(Sum(base_it_cli, filter=Q(transacciones__pagado=False), output_field=dec), zero),
                pend_desc=Coalesce(Sum(descnum_it_cli, filter=Q(transacciones__pagado=False), output_field=dec), zero),
                pend_abn=Coalesce(Sum("transacciones__abonos__valor", filter=Q(transacciones__pagado=False), output_field=dec), zero),
            )
            .annotate(pendiente=ExpressionWrapper(F("pend_base") - (F("pend_desc") / Decimal("100")) - F("pend_abn"), output_field=dec))
            .values("id", "nombre", "pendiente")
            .order_by("-pendiente", "nombre")
        )
        resumen_por_cliente = list(resumen_qs)

        # Sincroniza KPI con tabla (para que jamás veas $ vacío)
        valor_pendiente_tabla = sum((r["pendiente"] or Decimal("0")) for r in resumen_por_cliente)
        # Si quieres que el KPI siga estrictamente la tabla, usa:
        valor_pendiente = valor_pendiente_tabla

        # Select de cliente
        clientes_for_select = Cliente.objects.order_by("nombre").values("id", "nombre")

        ctx.update({
            # filtros actuales
            "f_cliente": int(cliente_id) if cliente_id.isdigit() else "",
            "f_mes": mes_code,
            "f_desde": d1,
            "f_hasta": d2,

            # KPIs
            "valor_pendiente": valor_pendiente,
            "facturas_pendientes": facturas_pendientes,
            "ventas_periodo": ventas_periodo,
            "tx_periodo": tx_periodo,
            "mejor_cliente_nombre": mejor_cliente_nombre,
            "mejor_cliente_total": mejor_cliente_total,
            "cliente_mas_cartera_nombre": cliente_mas_cartera_nombre,
            "cliente_mas_cartera_total": cliente_mas_cartera_total,

            # tabla
            "resumen_por_cliente": resumen_por_cliente,

            # selects
            "clientes_for_select": clientes_for_select,

            # otros
            "clientes_count": Cliente.objects.count(),
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

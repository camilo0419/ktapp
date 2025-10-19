from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy, reverse
from django.views.generic import ListView, DetailView, CreateView, UpdateView, TemplateView

from django.db.models import Q, Sum, F, Value as V, DecimalField, ExpressionWrapper
from django.db.models.functions import Coalesce

from .models import Cliente, Transaccion, Abono
from .forms import ClienteForm, TransaccionForm, AbonoForm, TransaccionItemFormSet
from .analytics import track


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
                Q(correo__icontains=q)   # corregido
            )
        # La plantilla no muestra totales, no anotamos nada aquí.
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

        # ---- Totales del cliente (usar ExpressionWrapper para evitar tipos mixtos) ----
        dec = DecimalField(max_digits=14, decimal_places=2)
        zero = V(Decimal("0.00"), output_field=dec)

        base_expr = ExpressionWrapper(
            F("items__precio_unitario") * F("items__cantidad"),
            output_field=dec,
        )
        desc_num_expr = ExpressionWrapper(
            F("items__precio_unitario") * F("items__cantidad") * F("items__descuento"),
            output_field=dec,
        )

        base_pag = tx.filter(pagado=True).aggregate(
            s=Coalesce(Sum(base_expr, output_field=dec), zero)
        )["s"] or Decimal("0.00")

        desc_num_pag = tx.filter(pagado=True).aggregate(
            s=Coalesce(Sum(desc_num_expr, output_field=dec), zero)
        )["s"] or Decimal("0.00")

        total_pagado = base_pag - (desc_num_pag / Decimal("100.00"))
        ctx["total_pagado"] = total_pagado

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


# ========= TRANSACCIONES =========

class TransaccionCreateView(LoginRequiredMixin, CreateView):
    model = Transaccion
    form_class = TransaccionForm
    template_name = "cartera/tx_form.html"

    def get_initial(self):
        ini = super().get_initial()
        cliente_id = self.request.GET.get("cliente")
        if cliente_id:
            ini["cliente"] = cliente_id
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
        formset = TransaccionItemFormSet(self.request.POST)
        if form.is_valid() and formset.is_valid():
            return self.forms_valid(form, formset)
        else:
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
        formset = TransaccionItemFormSet(self.request.POST, instance=self.object)
        if form.is_valid() and formset.is_valid():
            return self.forms_valid(form, formset)
        else:
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
    tx.marcar_pagado_ahora()
    tx.save()
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

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["transaccion"] = self.tx
        return kwargs

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.instance.transaccion = self.tx
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
from django.db.models.functions import Coalesce, Cast

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "cartera/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)

        dec = DecimalField(max_digits=14, decimal_places=2)
        zero = V(Decimal("0.00"), output_field=dec)

        # Expresiones para trabajar sobre Transaccion queryset
        base_tx = ExpressionWrapper(
            F("items__precio_unitario") * F("items__cantidad"),
            output_field=dec,
        )
        desc_pct_tx = Cast(F("items__descuento"), output_field=dec)
        desc_num_tx = ExpressionWrapper(base_tx * desc_pct_tx, output_field=dec)

        # ------ KPIs globales (sobre Transaccion) ------
        base_p = Transaccion.objects.aggregate(
            s=Coalesce(Sum(base_tx, filter=Q(pagado=False), output_field=dec), zero)
        )["s"] or Decimal("0.00")
        desc_num_p = Transaccion.objects.aggregate(
            s=Coalesce(Sum(desc_num_tx, filter=Q(pagado=False), output_field=dec), zero)
        )["s"] or Decimal("0.00")
        abonos_p = Transaccion.objects.aggregate(
            s=Coalesce(Sum("abonos__valor", filter=Q(pagado=False), output_field=dec), zero)
        )["s"] or Decimal("0.00")
        total_pendiente = base_p - (desc_num_p / Decimal("100.00")) - abonos_p

        base_g = Transaccion.objects.aggregate(
            s=Coalesce(Sum(base_tx, filter=Q(pagado=True), output_field=dec), zero)
        )["s"] or Decimal("0.00")
        desc_num_g = Transaccion.objects.aggregate(
            s=Coalesce(Sum(desc_num_tx, filter=Q(pagado=True), output_field=dec), zero)
        )["s"] or Decimal("0.00")
        total_pagado = base_g - (desc_num_g / Decimal("100.00"))

        # --------- Resumen por cliente (¡ojo al path correcto!) ----------
        base_cli = ExpressionWrapper(
            F("transacciones__items__precio_unitario") * F("transacciones__items__cantidad"),
            output_field=dec,
        )
        desc_pct_cli = Cast(F("transacciones__items__descuento"), output_field=dec)
        desc_num_cli = ExpressionWrapper(base_cli * desc_pct_cli, output_field=dec)

        clientes = (
            Cliente.objects
            .annotate(
                pend_base=Coalesce(Sum(base_cli, filter=Q(transacciones__pagado=False), output_field=dec), zero),
                pend_desc_num=Coalesce(Sum(desc_num_cli, filter=Q(transacciones__pagado=False), output_field=dec), zero),
                pend_abn=Coalesce(Sum("transacciones__abonos__valor", filter=Q(transacciones__pagado=False), output_field=dec), zero),
                pag_base=Coalesce(Sum(base_cli, filter=Q(transacciones__pagado=True), output_field=dec), zero),
                pag_desc_num=Coalesce(Sum(desc_num_cli, filter=Q(transacciones__pagado=True), output_field=dec), zero),
            )
            .values("id", "nombre", "pend_base", "pend_desc_num", "pend_abn", "pag_base", "pag_desc_num")
        )

        resumen = []
        for c in clientes:
            pendiente = (c["pend_base"] or Decimal("0")) - ((c["pend_desc_num"] or Decimal("0")) / Decimal("100")) - (c["pend_abn"] or Decimal("0"))
            pagado = (c["pag_base"] or Decimal("0")) - ((c["pag_desc_num"] or Decimal("0")) / Decimal("100"))
            resumen.append({
                "id": c["id"],
                "nombre": c["nombre"],
                "pendiente": pendiente,
                "pagado": pagado,
            })
        resumen.sort(key=lambda r: r["pendiente"], reverse=True)
        resumen = resumen[:50]

        ctx.update({
            "total_pendiente": total_pendiente,
            "total_pagado": total_pagado,
            "resumen_por_cliente": resumen,
            "clientes_count": Cliente.objects.count(),
        })
        return ctx
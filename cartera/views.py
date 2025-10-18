# cartera/views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView

from django.db.models import Q, Sum, F, Value, DecimalField, ExpressionWrapper
from django.db.models.functions import Coalesce

from .models import Cliente, Transaccion, Abono
from .forms import ClienteForm, TransaccionForm, AbonoForm
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
                Q(correo__icontains=q)
            )

        # Sumamos por separado y luego restamos (sin anidar agregados)
        qs = qs.annotate(
            total_valor=Coalesce(
                Sum("transacciones__valor", distinct=True),
                Value(0),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
            total_abonos=Coalesce(
                Sum("transacciones__abonos__valor"),
                Value(0),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            ),
        ).annotate(
            # ¡OJO! Alias distinto a la propiedad del modelo
            cartera_total=ExpressionWrapper(
                F("total_valor") - F("total_abonos"),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
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
            .prefetch_related("abonos")
            .order_by("-creado")
        )

        ctx["tx_list"] = tx
        ctx["total_pendiente"] = obj.saldo_pendiente
        ctx["total_pagado"] = tx.filter(pagado=True).aggregate(t=Sum("valor"))["t"] or 0
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
                "saldo_pend": obj.saldo_pendiente,
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

    def form_valid(self, form):
        resp = super().form_valid(form)
        track(
            self.request, "tx_create", "action",
            etiqueta=f"cliente_id={self.object.cliente_id}",
            extras={
                "tipo": self.object.tipo,
                "valor": float(self.object.valor),
                "pagado": self.object.pagado,
            },
        )
        messages.success(self.request, "Transacción creada.")
        return resp


class TransaccionUpdateView(LoginRequiredMixin, UpdateView):
    model = Transaccion
    form_class = TransaccionForm
    template_name = "cartera/tx_form.html"

    def get_success_url(self):
        return reverse_lazy("cartera:clientes_detail", args=[self.object.cliente_id])

    def form_valid(self, form):
        resp = super().form_valid(form)
        track(
            self.request, "tx_update", "action",
            etiqueta=f"tx_id={self.object.id}",
            extras={
                "tipo": self.object.tipo,
                "valor": float(self.object.valor),
                "pagado": self.object.pagado,
            },
        )
        messages.success(self.request, "Transacción actualizada.")
        return resp


@login_required
def transaccion_marcar_pagado(request, pk):
    tx = get_object_or_404(Transaccion, pk=pk)
    tx.marcar_pagado_ahora()
    tx.save()
    track(
        request, "tx_pagada", "action",
        etiqueta=f"tx_id={tx.id}",
        extras={"cliente_id": tx.cliente_id, "valor": float(tx.valor)},
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

    def form_valid(self, form):
        form.instance.transaccion = self.tx
        resp = super().form_valid(form)
        track(
            self.request, "abono_create", "action",
            etiqueta=f"tx_id={self.tx.id}",
            extras={"valor": float(self.object.valor), "saldo_post": self.tx.saldo_actual},
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

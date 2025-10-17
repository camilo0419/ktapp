# cartera/views.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import ListView, DetailView, CreateView, UpdateView
from django.db.models import Sum, Q
from .models import Cliente, Transaccion
from .forms import ClienteForm, TransaccionForm
from .analytics import track

class ClienteListView(LoginRequiredMixin, ListView):
    model = Cliente
    template_name = "cartera/clientes_list.html"
    context_object_name = "object_list"
    paginate_by = 10

    def get_queryset(self):
        q = self.request.GET.get("q", "").strip()
        qs = Cliente.objects.all()
        if q:
            qs = qs.filter(Q(nombre__icontains=q) | Q(telefono__icontains=q) | Q(correo__icontains=q))
        return qs.order_by("nombre")

    def get(self, request, *args, **kwargs):
        resp = super().get(request, *args, **kwargs)
        track(request,
              nombre="clientes_list",
              categoria="view",
              etiqueta=f"page={self.request.GET.get('page','1')}",
              extras={"q": self.request.GET.get("q", "")})
        return resp


class ClienteCreateView(LoginRequiredMixin, CreateView):
    model = Cliente
    form_class = ClienteForm
    template_name = "cartera/cliente_form.html"
    success_url = reverse_lazy("cartera:clientes_list")

    def form_valid(self, form):
        resp = super().form_valid(form)
        track(self.request, "cliente_create", "action",
              etiqueta=f"cliente_id={self.object.id}", extras={"nombre": self.object.nombre})
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
              etiqueta=f"cliente_id={self.object.id}", extras={"activo": self.object.activo})
        messages.success(self.request, "Cliente actualizado.")
        return resp


class ClienteDetailView(LoginRequiredMixin, DetailView):
    model = Cliente
    template_name = "cartera/cliente_detail.html"
    context_object_name = "obj"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        obj = self.object
        tx = obj.transacciones.all().order_by("-creado")
        # KPIs rápidos para analytics y dashboard
        ctx["total_pendiente"] = tx.filter(pagado=False).aggregate(t=Sum("valor"))["t"] or 0
        ctx["total_pagado"] = tx.filter(pagado=True).aggregate(t=Sum("valor"))["t"] or 0
        ctx["tx_count"] = tx.count()
        ctx["tx_list"] = tx
        return ctx

    def get(self, request, *args, **kwargs):
        resp = super().get(request, *args, **kwargs)
        obj = self.object
        track(request, "cliente_detail", "view",
              etiqueta=f"cliente_id={obj.id}",
              extras={
                  "saldo_pend": obj.saldo_pendiente,
                  "tx_total": obj.transacciones.count(),
              })
        return resp


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
        track(self.request, "tx_create", "action",
              etiqueta=f"cliente_id={self.object.cliente_id}",
              extras={
                  "tipo": self.object.tipo,
                  "valor": float(self.object.valor),
                  "pagado": self.object.pagado,
              })
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
        track(self.request, "tx_update", "action",
              etiqueta=f"tx_id={self.object.id}",
              extras={
                  "tipo": self.object.tipo,
                  "valor": float(self.object.valor),
                  "pagado": self.object.pagado,
              })
        messages.success(self.request, "Transacción actualizada.")
        return resp


@login_required
def transaccion_marcar_pagado(request, pk):
    tx = get_object_or_404(Transaccion, pk=pk)
    tx.marcar_pagado_ahora()
    tx.save()
    track(request, "tx_pagada", "action",
          etiqueta=f"tx_id={tx.id}",
          extras={"cliente_id": tx.cliente_id, "valor": float(tx.valor)})
    messages.success(request, "Transacción marcada como pagada.")
    return redirect("cartera:clientes_detail", pk=tx.cliente_id)

from django import forms
from django.utils import timezone
from .models import Cliente, Transaccion, Abono
from django.core.exceptions import ValidationError

class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ["nombre", "telefono", "correo", "activo"]


class TransaccionForm(forms.ModelForm):
    class Meta:
        model = Transaccion
        fields = [
            "cliente", "tipo", "campania", "descripcion", "valor",
            "pagado", "fecha_pago", "hora_pago", "notas"
        ]
        widgets = {
            "fecha_pago": forms.DateInput(attrs={"type": "date"}),
            "hora_pago": forms.TimeInput(attrs={"type": "time"}),
            "notas": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["valor"].widget.attrs.update({
            "inputmode": "numeric", "placeholder": "$ 0", "min": "0", "max": "10000000", "step": "0.01"
        })
        self.fields["descripcion"].widget.attrs.update({"placeholder": "Ej: Labial Rojo", "maxlength": "200"})

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("pagado"):
            cleaned["fecha_pago"] = cleaned.get("fecha_pago") or timezone.localdate()
            cleaned["hora_pago"] = cleaned.get("hora_pago") or timezone.localtime().time()
        return cleaned


class AbonoForm(forms.ModelForm):
    class Meta:
        model = Abono
        fields = ["valor", "metodo", "fecha", "hora", "notas"]
        widgets = {
            "fecha": forms.DateInput(attrs={"type": "date"}),
            "hora": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, **kwargs):
        self.transaccion = kwargs.pop("transaccion", None)
        super().__init__(*args, **kwargs)
        self.fields["valor"].widget.attrs.update({"inputmode": "numeric", "min": "0", "step": "0.01"})

    def clean(self):
        cleaned = super().clean()
        if not self.transaccion and not self.instance.transaccion_id:
            raise ValidationError("Falta transacción para el abono.")
        tx = self.transaccion or self.instance.transaccion
        valor = float(cleaned.get("valor") or 0)
        if valor <= 0:
            self.add_error("valor", "El abono debe ser mayor que 0.")
        restante = tx.saldo_actual
        if valor - restante > 1e-6:
            self.add_error("valor", f"El abono ({valor:.0f}) excede el saldo ({restante:.0f}).")
        return cleaned

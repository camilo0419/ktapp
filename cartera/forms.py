# cartera/forms.py
from django import forms
from django.utils import timezone
from .models import Cliente, Transaccion

class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ["nombre", "telefono", "correo", "activo"]

class TransaccionForm(forms.ModelForm):
    class Meta:
        model = Transaccion
        fields = [
            "cliente", "tipo", "campania", "valor",
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
            "inputmode": "numeric",
            "placeholder": "$ 0",
            "min": "0", "max": "10000000", "step": "0.01"
        })

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("pagado"):
            if not cleaned.get("fecha_pago"):
                cleaned["fecha_pago"] = timezone.localdate()
            if not cleaned.get("hora_pago"):
                cleaned["hora_pago"] = timezone.localtime().time()
        return cleaned

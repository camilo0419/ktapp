from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory

from .models import Cliente, Transaccion, Abono, TransaccionItem


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ["nombre", "telefono", "correo", "activo"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "input", "placeholder": "Razón social o nombre", "autocomplete": "name"}),
            "telefono": forms.TextInput(attrs={"class": "input", "placeholder": "Teléfono"}),
            "correo": forms.EmailInput(attrs={"class": "input", "placeholder": "Correo"}),
            "activo": forms.CheckboxInput(attrs={"class": "checkbox"}),
        }


class TransaccionForm(forms.ModelForm):
    class Meta:
        model = Transaccion
        fields = ["cliente", "tipo", "campania", "fecha", "hora", "pagado"]
        widgets = {
            "cliente": forms.Select(attrs={"class": "input"}),
            "tipo": forms.Select(attrs={"class": "input", "id": "id_tipo"}),
            "campania": forms.TextInput(attrs={"class": "input", "placeholder": "# Campaña", "id": "id_campania"}),
            "fecha": forms.DateInput(attrs={"type": "date", "class": "input"}),
            "hora": forms.HiddenInput(),  # oculto
            "pagado": forms.CheckboxInput(attrs={"class": "checkbox", "id": "id_pagado"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # ⚠️ clave: el form no exigirá 'hora'; el modelo pone el default al guardar
        self.fields["hora"].required = False

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("tipo") == Transaccion.NATURA and not (cleaned.get("campania") or "").strip():
            self.add_error("campania", "Para Natura debes indicar # Campaña.")
        return cleaned


class TransaccionItemForm(forms.ModelForm):
    # aseguramos que el campo NO sea requerido (blank=True en el modelo) y que el select tenga opción vacía
    descuento = forms.ChoiceField(
        required=False,
        choices=[("", "—")] + [(str(k), v) for k, v in TransaccionItem.DESCUENTOS],
        widget=forms.Select(attrs={"class": "input"}),
        label="Descuento %"
    )

    class Meta:
        model = TransaccionItem
        fields = ["producto", "precio_unitario", "cantidad", "descuento"]
        widgets = {
            "producto": forms.TextInput(attrs={"class": "input", "placeholder": "Producto"}),
            "precio_unitario": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0"}),
            "cantidad": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0"}),
        }

    def clean_descuento(self):
        v = self.cleaned_data.get("descuento")
        if v in (None, "", "None"):
            return None
        try:
            v_int = int(v)
        except Exception:
            raise ValidationError("Descuento inválido.")
        if v_int not in (10, 20, 30):
            raise ValidationError("Solo 10%, 20% o 30%.")
        return v_int


TransaccionItemFormSet = inlineformset_factory(
    Transaccion,
    TransaccionItem,
    form=TransaccionItemForm,
    extra=1,          # solo 1 fila por defecto
    can_delete=True,
    min_num=1,
    validate_min=True,
)


class AbonoForm(forms.ModelForm):
    class Meta:
        model = Abono
        fields = ["valor", "metodo", "fecha", "hora", "notas"]
        widgets = {
            "valor": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0"}),
            "metodo": forms.Select(attrs={"class": "input"}),
            "fecha": forms.DateInput(attrs={"type": "date", "class": "input"}),
            "hora": forms.TimeInput(attrs={"type": "time", "class": "input"}),
            "notas": forms.TextInput(attrs={"class": "input", "placeholder": "Notas"}),
        }

    def __init__(self, *args, **kwargs):
        self.transaccion = kwargs.pop("transaccion", None)
        super().__init__(*args, **kwargs)

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

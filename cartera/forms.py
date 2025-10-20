from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory, BaseInlineFormSet

from .models import Cliente, Transaccion, Abono, TransaccionItem
from django.utils import timezone


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
    # Asegura el formato del <input type="date">
    fecha = forms.DateField(
        required=True,
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date", "class": "input"})
    )

    class Meta:
        model = Transaccion
        fields = ["cliente", "tipo", "campania", "fecha", "hora", "pagado"]
        widgets = {
            "cliente": forms.Select(attrs={"class": "input"}),
            "tipo": forms.Select(attrs={"class": "input", "id": "id_tipo"}),
            "campania": forms.TextInput(attrs={"class": "input", "placeholder": "# Campaña", "id": "id_campania"}),
            "hora": forms.HiddenInput(),
            "pagado": forms.CheckboxInput(attrs={"class": "checkbox", "id": "id_pagado"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["hora"].required = False

        # Crear: precargar hoy
        if not self.is_bound and not self.instance.pk and not self.initial.get("fecha"):
            self.initial["fecha"] = timezone.localdate()

        # Editar (GET): pintar la fecha existente en formato YYYY-MM-DD
        if not self.is_bound and self.instance.pk and getattr(self.instance, "fecha", None):
            self.initial["fecha"] = self.instance.fecha.strftime("%Y-%m-%d")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("tipo") == Transaccion.NATURA and not (cleaned.get("campania") or "").strip():
            self.add_error("campania", "Para Natura debes indicar # Campaña.")
        return cleaned


class TransaccionItemForm(forms.ModelForm):
    # Campos no requeridos por defecto: validamos en el formset
    producto = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "input", "placeholder": "Producto"}),
        label="Producto",
    )
    precio_unitario = forms.DecimalField(
        required=False, min_value=0,
        widget=forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0"}),
        label="Precio U.",
    )
    cantidad = forms.DecimalField(
        required=False, min_value=0,
        widget=forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0"}),
        label="Cantidad",
    )
    # opción vacía + 10/20/30
    descuento = forms.ChoiceField(
        required=False,
        choices=[("", "—")] + [(str(k), v) for k, v in TransaccionItem.DESCUENTOS],
        widget=forms.Select(attrs={"class": "input"}),
        label="Descuento %"
    )

    class Meta:
        model = TransaccionItem
        fields = ["producto", "precio_unitario", "cantidad", "descuento"]

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


class TransaccionItemBaseFormSet(BaseInlineFormSet):
    """
    - Ignora filas totalmente vacías (no estorban).
    - Si una fila viene 'a medias', marca errores en sus campos faltantes.
    - Exige al menos 1 fila completa (producto + precio + cantidad).
    """
    def clean(self):
        super().clean()
        completos = 0

        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            if form.cleaned_data.get("DELETE"):
                continue

            producto = form.cleaned_data.get("producto")
            precio   = form.cleaned_data.get("precio_unitario")
            cantidad = form.cleaned_data.get("cantidad")
            # descuento puede ser None o 10/20/30 — no lo usamos para definir “completo”

            # Fila totalmente vacía → ignorar (no marca errores)
            if not producto and precio in (None, "") and cantidad in (None, ""):
                # asegurar que pase sin errores
                form._errors = getattr(form, "_errors", None) or {}
                continue

            # Si hay algo escrito, pedimos los 3 campos
            if not producto:
                form.add_error("producto", "Este campo es obligatorio.")
            if precio in (None, ""):
                form.add_error("precio_unitario", "Este campo es obligatorio.")
            if cantidad in (None, ""):
                form.add_error("cantidad", "Este campo es obligatorio.")

            # Si no quedaron errores en la fila, la contamos como completa
            if not form.errors:
                completos += 1

        if completos == 0:
            raise ValidationError("Agrega al menos un producto completo.")


TransaccionItemFormSet = inlineformset_factory(
    Transaccion,
    TransaccionItem,
    form=TransaccionItemForm,
    formset=TransaccionItemBaseFormSet,
    extra=1,          # 1 línea visible por defecto
    can_delete=True,
    validate_min=False,  # validación la hacemos en clean()
)
# (No usamos min_num/validate_min para que filas vacías no rompan)
# La regla de "al menos 1 producto" queda en TransaccionItemBaseFormSet.clean()


from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
# ... (tus imports arriba se quedan iguales)

class AbonoForm(forms.ModelForm):
    # Declaramos los campos con formato explícito que coincide con <input type="date/time">
    fecha = forms.DateField(
        required=False,
        widget=forms.DateInput(
            format="%Y-%m-%d",                  # <-- clave para que el valor se pinte
            attrs={"type": "date", "class": "input"},
        ),
        input_formats=["%Y-%m-%d"],            # <-- clave para que lo reciba igual
    )
    hora = forms.TimeField(
        required=False,
        widget=forms.TimeInput(
            format="%H:%M",                     # muestra HH:MM (24h)
            attrs={"type": "time", "class": "input"},
        ),
        input_formats=["%H:%M", "%H:%M:%S"],   # acepta HH:MM o HH:MM:SS
    )

    class Meta:
        model = Abono
        fields = ["valor", "metodo", "fecha", "hora", "notas"]
        widgets = {
            "valor": forms.NumberInput(attrs={"class": "input", "step": "0.01", "min": "0"}),
            "metodo": forms.Select(attrs={"class": "input"}),
            "notas": forms.TextInput(attrs={"class": "input", "placeholder": "Notas"}),
        }

    def __init__(self, *args, **kwargs):
        self.transaccion = kwargs.pop("transaccion", None)
        super().__init__(*args, **kwargs)

        # Precarga en GET (no bound). Como definimos format arriba, se verá en el input.
        if not self.is_bound:
            self.initial.setdefault("fecha", timezone.localdate())                     # -> YYYY-MM-DD en el input
            self.initial.setdefault("hora",  timezone.localtime().replace(microsecond=0).time())

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
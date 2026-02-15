# cartera/models.py
from decimal import Decimal
from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models import Sum, Value as V, DecimalField, F
from django.db.models.functions import Coalesce

def current_local_date():
    return timezone.localdate()

def current_local_time():
    return timezone.localtime().time()


class Cliente(models.Model):
    nombre   = models.CharField(max_length=120)
    telefono = models.CharField(max_length=30, blank=True)
    correo   = models.EmailField(blank=True)
    activo   = models.BooleanField(default=True)
    creado   = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["telefono"],
                condition=~models.Q(telefono=""),
                name="uniq_cliente_telefono_no_vacio",
            ),
        ]


    def __str__(self):
        return self.nombre

    @property
    def total_pendiente(self):
        total = 0
        for tx in self.transacciones.all().prefetch_related("items", "abonos"):
            if not tx.pagado:
                total += tx.saldo_actual
        return total


class Transaccion(models.Model):
    NATURA      = "NAT"
    ACCESORIOS  = "ACC"
    OTROS       = "OTR"
    TIPOS = [
        (NATURA, "Natura"),
        (ACCESORIOS, "Accesorios"),
        (OTROS, "Otros"),
    ]

    cliente  = models.ForeignKey(Cliente, related_name="transacciones", on_delete=models.PROTECT)
    fecha    = models.DateField(default=current_local_date)
    hora     = models.TimeField(default=current_local_time)
    tipo     = models.CharField(max_length=3, choices=TIPOS, default=OTROS)
    campania = models.CharField(max_length=80, blank=True)

    pagado    = models.BooleanField(default=False)
    pagado_en = models.DateTimeField(blank=True, null=True)
    fecha_pago = models.DateField(blank=True, null=True)

    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado"]

    def __str__(self):
        return f"TX #{self.pk} - {self.cliente} - {self.fecha}"

    # ----- Totales con % de descuento en ítems -----
    @property
    def subtotal_items(self) -> float:
        dec = DecimalField(max_digits=14, decimal_places=2)
        zero = V(Decimal("0.00"), output_field=dec)
        return float(self.items.aggregate(
            s=Coalesce(Sum(F("precio_unitario") * F("cantidad"), output_field=dec), zero)
        )["s"] or Decimal("0.00"))

    @property
    def total_lineas(self) -> float:
        # suma de cada línea con descuento % aplicado
        total = 0.0
        for it in self.items.all():
            total += it.total_linea
        return total

    @property
    def total_descuento_items(self) -> float:
        # subtotal - total_lineas
        return max(self.subtotal_items - self.total_lineas, 0.0)

    @property
    def valor_a_pagar(self) -> float:
        # el que suma a cartera si no está pagado
        return max(self.total_lineas, 0.0)

    @property
    def total_abonos(self) -> float:
        dec = DecimalField(max_digits=14, decimal_places=2)
        zero = V(Decimal("0.00"), output_field=dec)
        return float(self.abonos.aggregate(
            s=Coalesce(Sum("valor", output_field=dec), zero)
        )["s"] or Decimal("0.00"))

    @property
    def saldo_actual(self) -> float:
        # Si la transacción está marcada como pagada, el saldo es 0
        if self.pagado:
            return 0.0
        return max(self.valor_a_pagar - self.total_abonos, 0.0)

    def clean(self):
        if self.tipo == self.NATURA and not (self.campania or "").strip():
            raise ValidationError({"campania": "Para Natura debes indicar # Campaña."})

    def save(self, *args, **kwargs):
        if self.pagado and self.pagado_en is None:
            self.pagado_en = timezone.now()
        if not self.pagado:
            self.pagado_en = None
        super().save(*args, **kwargs)


class TransaccionItem(models.Model):
    DESCUENTOS = [(10, "10%"), (20, "20%"), (30, "30%")]

    transaccion     = models.ForeignKey(Transaccion, related_name="items", on_delete=models.CASCADE)
    codigo_producto = models.CharField(max_length=40, blank=True)
    producto        = models.CharField(max_length=200)
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)], default=0)
    cantidad        = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)], default=1)
    # % de descuento SOLO 10/20/30; si viene None, se interpreta como 0%
    descuento       = models.PositiveSmallIntegerField(choices=DESCUENTOS, null=True, blank=True)

    class Meta:
        verbose_name = "Ítem de transacción"
        verbose_name_plural = "Ítems de transacción"

    def __str__(self):
        return f"{self.producto} x {self.cantidad}"

    def save(self, *args, **kwargs):
        # Normalizar a 'Solo mayúscula inicial'
        if self.producto is not None:
            p = str(self.producto).strip()
            if p:
                self.producto = p[:1].upper() + p[1:].lower()
        super().save(*args, **kwargs)

    @property
    def total_linea(self) -> float:
        base = float(self.precio_unitario) * float(self.cantidad)
        pct  = (self.descuento or 0) / 100.0
        return max(base * (1.0 - pct), 0.0)


class Abono(models.Model):
    NEQUI = "NEQ"
    BANCOLOMBIA = "BAN"
    EFECTIVO = "EFE"
    CRUCE = "CRU"

    METODOS = [
        (NEQUI, "Nequi"),
        (BANCOLOMBIA, "Bancolombia"),
        (EFECTIVO, "Efectivo"),
        (CRUCE, "Cruce de cuentas"),
    ]

    transaccion = models.ForeignKey(Transaccion, related_name="abonos", on_delete=models.CASCADE)
    valor       = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    metodo      = models.CharField(max_length=3, choices=METODOS, default=BANCOLOMBIA)
    descripcion_cruce = models.CharField(max_length=240, blank=True)
    fecha       = models.DateField(default=current_local_date)
    hora        = models.TimeField(default=current_local_time)
    notas       = models.CharField(max_length=200, blank=True)
    creado      = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado"]

    
    def clean(self):
        if self.metodo == self.CRUCE and not (self.descripcion_cruce or "").strip():
            raise ValidationError({"descripcion_cruce": "Indica la descripción del cruce de cuentas."})

    def __str__(self):
        return f"Abono {self.valor:.0f} a TX #{self.transaccion_id}"

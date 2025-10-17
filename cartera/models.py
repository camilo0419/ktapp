# cartera/models.py
from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db.models import Sum, Value, DecimalField
from django.db.models.functions import Coalesce


# --- Helpers de tiempo para defaults serializables ---
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
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre

    @property
    def saldo_pendiente(self):
        """
        Suma de (valor - total_abonado) para transacciones con saldo > 0.
        Usa Decimal coherente para evitar 'mixed types'.
        """
        tx_vals = (
            self.transacciones
            .annotate(
                total_abonos=Coalesce(
                    Sum("abonos__valor"),
                    Value(0),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                )
            )
            .values_list("valor", "total_abonos")
        )
        total = 0.0
        for valor, total_abonos in tx_vals:
            saldo_tx = float(valor) - float(total_abonos or 0)
            if saldo_tx > 1e-6:
                total += saldo_tx
        return total


class Transaccion(models.Model):
    NATURA = "NAT"
    ACCESORIOS = "ACC"
    OTROS = "OTR"
    TIPOS = [
        (NATURA, "Natura"),
        (ACCESORIOS, "Accesorios"),
        (OTROS, "Otros"),
    ]

    cliente = models.ForeignKey(Cliente, related_name="transacciones", on_delete=models.CASCADE)
    tipo = models.CharField(max_length=3, choices=TIPOS)
    campania = models.CharField(max_length=20, blank=True)
    descripcion = models.CharField(max_length=200, blank=True)

    valor = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(10_000_000)]
    )

    # Estado de pago (se recalcula con abonos)
    pagado = models.BooleanField(default=False)
    fecha_pago = models.DateField(blank=True, null=True)
    hora_pago = models.TimeField(blank=True, null=True)

    notas = models.TextField(blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado"]

    def __str__(self):
        return f"TX #{self.pk} - {self.cliente.nombre} - {self.get_tipo_display()}"

    def clean(self):
        if self.tipo == self.NATURA and not self.campania:
            raise ValidationError({"campania": "La campaña es obligatoria para Natura."})

    @property
    def total_abonado(self):
        agg = self.abonos.aggregate(
            t=Coalesce(
                Sum("valor"),
                Value(0),
                output_field=DecimalField(max_digits=12, decimal_places=2),
            )
        )
        return float(agg["t"] or 0)

    @property
    def saldo_actual(self):
        saldo = float(self.valor) - self.total_abonado
        return max(saldo, 0.0)

    def marcar_pagado_ahora(self):
        self.pagado = True
        now = timezone.localtime()
        self.fecha_pago = self.fecha_pago or now.date()
        self.hora_pago  = self.hora_pago  or now.time()

    def recomputar_pagado(self, persist=True):
        """
        Si total_abonado >= valor -> pagado=True (y set fecha/hora si faltan).
        Si no, pagado=False (y limpiamos fecha/hora).
        """
        if self.total_abonado + 1e-6 >= float(self.valor):
            if not self.pagado:
                self.marcar_pagado_ahora()
        else:
            self.pagado = False
            self.fecha_pago = None
            self.hora_pago = None
        if persist:
            self.save(update_fields=["pagado", "fecha_pago", "hora_pago"])


class Abono(models.Model):
    EFECTIVO = "EFE"
    TRANSFER = "TRF"
    OTRO = "OTR"
    METODOS = [
        (EFECTIVO, "Efectivo"),
        (TRANSFER, "Transferencia"),
        (OTRO, "Otro"),
    ]

    transaccion = models.ForeignKey(Transaccion, related_name="abonos", on_delete=models.CASCADE)
    valor = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    metodo = models.CharField(max_length=3, choices=METODOS, default=TRANSFER)
    fecha = models.DateField(default=current_local_date)
    hora = models.TimeField(default=current_local_time)
    notas = models.CharField(max_length=200, blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado"]

    def __str__(self):
        return f"Abono #{self.pk} TX {self.transaccion_id} - {self.valor}"

    def clean(self):
        if float(self.valor) <= 0:
            raise ValidationError({"valor": "El abono debe ser mayor que 0."})
        # Evitar sobrepago
        restante = self.transaccion.saldo_actual
        if float(self.valor) - restante > 1e-6:
            raise ValidationError({"valor": f"El abono ({self.valor}) excede el saldo ({restante:.0f})."})

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Recalcular estado de la transacción tras guardar
        self.transaccion.recomputar_pagado(persist=True)

    def delete(self, *args, **kwargs):
        tx = self.transaccion
        super().delete(*args, **kwargs)
        # Recalcular estado tras borrar
        tx.recomputar_pagado(persist=True)


class EventoAnalitica(models.Model):
    """
    Registro de eventos de servidor (pageviews, acciones de CRUD, filtros, etc.)
    Pensado para dashboards internos.
    """
    ts = models.DateTimeField(auto_now_add=True)
    nombre = models.CharField(max_length=80)        # 'clientes_list', 'tx_create', 'abono_create', etc.
    categoria = models.CharField(max_length=40)     # 'view', 'action', 'error', ...
    etiqueta = models.CharField(max_length=120, blank=True)
    valor = models.FloatField(blank=True, null=True)
    extras = models.JSONField(blank=True, null=True)
    path = models.CharField(max_length=255, blank=True)
    metodo = models.CharField(max_length=8, blank=True)
    ip = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["ts"]),
            models.Index(fields=["nombre", "categoria"]),
        ]

    def __str__(self):
        return f"[{self.ts:%Y-%m-%d %H:%M}] {self.categoria}:{self.nombre} ({self.etiqueta})"

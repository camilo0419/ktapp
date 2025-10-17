# cartera/models.py
from django.db import models
from django.core.validators import MaxValueValidator, MinValueValidator
from django.utils import timezone
from django.core.exceptions import ValidationError

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
        agg = self.transacciones.filter(pagado=False).aggregate(total=models.Sum("valor"))
        return agg["total"] or 0


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
    valor = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(10_000_000)]
    )
    pagado = models.BooleanField(default=False)
    fecha_pago = models.DateField(blank=True, null=True)
    hora_pago = models.TimeField(blank=True, null=True)
    notas = models.TextField(blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado"]

    def clean(self):
        if self.tipo == self.NATURA and not self.campania:
            raise ValidationError({"campania": "La campaña es obligatoria para Natura."})

    def marcar_pagado_ahora(self):
        self.pagado = True
        now = timezone.localtime()
        self.fecha_pago = now.date()
        self.hora_pago = now.time()


class EventoAnalitica(models.Model):
    """
    Registro de eventos de servidor (pageviews, acciones de CRUD, filtros, etc.)
    Pensado para tus dashboards.
    """
    ts = models.DateTimeField(auto_now_add=True)
    nombre = models.CharField(max_length=80)      # ej: 'clientes_list', 'tx_create', 'tx_pagada'
    categoria = models.CharField(max_length=40)   # ej: 'view', 'action'
    etiqueta = models.CharField(max_length=120, blank=True)  # ej: 'cliente=12'
    valor = models.FloatField(blank=True, null=True)         # ej: total, duración, contador
    extras = models.JSONField(blank=True, null=True)         # payload adicional
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

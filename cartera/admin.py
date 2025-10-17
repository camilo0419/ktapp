from django.contrib import admin
from .models import Cliente, Transaccion, Abono, EventoAnalitica

@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("id", "nombre", "telefono", "correo", "activo", "creado")
    search_fields = ("nombre", "telefono", "correo")
    list_filter = ("activo",)

@admin.register(Transaccion)
class TransaccionAdmin(admin.ModelAdmin):
    list_display = ("id", "cliente", "tipo", "campania", "descripcion", "valor",
                    "pagado", "fecha_pago", "hora_pago", "creado")
    list_filter = ("tipo", "pagado")
    search_fields = ("cliente__nombre", "campania", "descripcion", "notas")

@admin.register(Abono)
class AbonoAdmin(admin.ModelAdmin):
    list_display = ("id", "transaccion", "valor", "metodo", "fecha", "hora", "creado")
    list_filter = ("metodo", "fecha")
    search_fields = ("transaccion__cliente__nombre", "notas")

@admin.register(EventoAnalitica)
class EventoAnaliticaAdmin(admin.ModelAdmin):
    list_display = ("ts", "categoria", "nombre", "etiqueta", "valor")
    list_filter = ("categoria", "nombre")
    search_fields = ("etiqueta", "path", "user_agent")
    date_hierarchy = "ts"

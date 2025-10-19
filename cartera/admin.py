from django.contrib import admin

# Importa lo seguro que ya existe
from .models import Cliente, Transaccion, Abono

# Importa condicionalmente por si aún no has creado/migrado estos modelos
try:
    from .models import TransaccionItem  # nuevo detalle de productos
except Exception:
    TransaccionItem = None

try:
    from .models import EventoAnalitica  # si en algún momento lo vuelves a crear
except Exception:
    EventoAnalitica = None


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("id", "nombre", "telefono", "correo", "activo")
    search_fields = ("nombre", "telefono", "correo")
    list_filter = ("activo",)


# Inlines opcionales (solo si TransaccionItem existe)
class _TransaccionItemInline(admin.TabularInline):
    model = TransaccionItem
    extra = 0

@admin.register(Transaccion)
class TransaccionAdmin(admin.ModelAdmin):
    list_display = ("id", "cliente", "fecha", "hora", "pagado", "pagado_en")
    list_filter = ("pagado", "fecha")
    search_fields = ("cliente__nombre",)
    # agrega inline si el modelo existe
    inlines = [_TransaccionItemInline] if TransaccionItem else []


@admin.register(Abono)
class AbonoAdmin(admin.ModelAdmin):
    list_display = ("id", "transaccion", "valor", "metodo", "fecha", "hora")
    list_filter = ("metodo", "fecha")
    search_fields = ("transaccion__cliente__nombre",)


# Registro condicional (para no romper si el modelo no existe)
if TransaccionItem:
    @admin.register(TransaccionItem)
    class TransaccionItemAdmin(admin.ModelAdmin):
        list_display = ("id", "transaccion", "producto", "precio_unitario", "cantidad", "descuento")
        search_fields = ("producto",)
        list_filter = ("transaccion__fecha",)

# Si algún día agregas EventoAnalitica de nuevo, se registrará automáticamente:
if EventoAnalitica:
    @admin.register(EventoAnalitica)
    class EventoAnaliticaAdmin(admin.ModelAdmin):
        list_display = ("id", "nombre", "categoria", "creado")

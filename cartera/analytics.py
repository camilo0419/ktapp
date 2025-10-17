# cartera/analytics.py
from .models import EventoAnalitica

def _client_ip(request):
    """
    Extrae la IP del cliente respetando posibles proxys.
    """
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        # Formato típico: "ip_real, proxy1, proxy2"
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")

def track(request, nombre, categoria="view", etiqueta="", valor=None, extras=None):
    """
    Registra un evento de analytics de servidor.
    - nombre: string corto del evento (ej: 'clientes_list', 'tx_create')
    - categoria: 'view' | 'action' | 'error' | lo que prefieras
    - etiqueta: texto corto adicional (ej: 'cliente_id=12')
    - valor: numérico opcional (para métricas)
    - extras: dict con payload adicional (quedará en JSONField)
    """
    try:
        EventoAnalitica.objects.create(
            nombre=nombre[:80],
            categoria=categoria[:40] if categoria else "",
            etiqueta=(etiqueta or "")[:120],
            valor=valor,
            extras=extras or {},
            path=(getattr(request, "path", "") or "")[:255],
            metodo=(getattr(request, "method", "") or "")[:8],
            ip=_client_ip(request),
            user_agent=(request.META.get("HTTP_USER_AGENT", "") or "")[:500],
        )
    except Exception:
        # Nunca romper la UX por analytics
        pass

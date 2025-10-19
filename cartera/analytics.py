# cartera/analytics.py
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

def track(
    request,
    nombre: str,
    categoria: str,
    etiqueta: str = "",
    valor: Optional[float] = None,
    extras: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Registrador 'best-effort' que NO depende de modelos.
    Es seguro en migraciones y en arranque temprano del proyecto.
    """
    try:
        data = {
            "user": getattr(getattr(request, "user", None), "id", None),
            "ip": _client_ip(request),
            "nombre": nombre,
            "categoria": categoria,
            "etiqueta": etiqueta,
            "valor": valor,
            "extras": extras or {},
        }
        logger.info("[analytics] %s", data)
    except Exception:
        logger.exception("[analytics] Falló el track() pero se ignora para no romper la app.")


def _client_ip(request) -> Optional[str]:
    try:
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        if xff:
            return xff.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")
    except Exception:
        return None

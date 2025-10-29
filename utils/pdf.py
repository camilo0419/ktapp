# utils/pdf.py
import os
from django.conf import settings
from django.contrib.staticfiles import finders

def link_callback(uri, rel):
    """
    Convierte URIs de /static/ y /media/ a rutas absolutas en disco.
    Sirve tanto en local (sin collectstatic) como en producción.
    """
    # 1) STATIC
    if uri.startswith(settings.STATIC_URL):
        # a) Intento por STATIC_ROOT (producción)
        rel_path = uri.replace(settings.STATIC_URL, "")
        if settings.STATIC_ROOT:
            path = os.path.join(settings.STATIC_ROOT, rel_path)
            if os.path.isfile(path):
                return path
        # b) Fallback en local: buscar con finders (sin collectstatic)
        found = finders.find(rel_path)
        if found:
            return found
        # Último recurso: si es una ruta absoluta válida, devuélvela
        if os.path.isfile(uri):
            return uri
        raise FileNotFoundError(f"[xhtml2pdf] STATIC no encontrado: {uri}")

    # 2) MEDIA (si lo usas)
    if getattr(settings, "MEDIA_URL", None) and uri.startswith(settings.MEDIA_URL):
        rel_path = uri.replace(settings.MEDIA_URL, "")
        if settings.MEDIA_ROOT:
            path = os.path.join(settings.MEDIA_ROOT, rel_path)
            if os.path.isfile(path):
                return path
        if os.path.isfile(uri):
            return uri
        raise FileNotFoundError(f"[xhtml2pdf] MEDIA no encontrado: {uri}")

    # 3) Rutas absolutas locales o file://
    if uri.startswith("file://"):
        local_path = uri[7:]
        if os.path.isfile(local_path):
            return local_path
    if os.path.isabs(uri) and os.path.isfile(uri):
        return uri

    # Si llega aquí, déjalo tal cual (por si el motor lo entiende)
    return uri

# ktapp/ktapp/settings_prod.py
from .settings import *   # hereda lo local/base y solo sobreescribe lo necesario
import os

# --- Core ---
DEBUG = False
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "change-me-in-PA")

ALLOWED_HOSTS = ["kathem.pythonanywhere.com"]
CSRF_TRUSTED_ORIGINS = ["https://kathem.pythonanywhere.com"]

PDF_ENGINE = "weasyprint"


# --- Seguridad (recomendado en PA) ---
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# Si tu app está detrás de proxy (PA), esto ayuda a detectar HTTPS:
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- Archivos estáticos ---
# BASE_DIR ya viene de settings base
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# En el panel Web de PA, mapea /static/ -> /home/kathem/ktapp/staticfiles

# --- DB ---
# Si usas SQLite (por defecto), queda igual que en settings base (db.sqlite3).
# Si migras a MySQL en PA, sobreescribe aquí DATABASES.

# --- Zona horaria / idioma (opcional si ya está en base) ---
# TIME_ZONE = "America/Bogota"
# LANGUAGE_CODE = "es-co"

# --- Django Admin y otros ---
# DEFAULT_AUTO_FIELD ya viene del base

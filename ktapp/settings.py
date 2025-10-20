import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Seguridad / entorno
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-secret-key-cambia-esto")
DEBUG = os.environ.get("DJANGO_DEBUG", "False") == "True"

ALLOWED_HOSTS = [
    "kathem.pythonanywhere.com",
    "www.kathem.pythonanywhere.com",
]

# Django 4/5: importante para formularios en HTTPS
CSRF_TRUSTED_ORIGINS = ["https://kathem.pythonanywhere.com"]

# --- Apps
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "cartera",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # (Opcional en prod) "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "ktapp.urls"
WSGI_APPLICATION = "ktapp.wsgi.application"

# --- Base de datos (SQLite)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# --- Localización
LANGUAGE_CODE = "es"
TIME_ZONE = "America/Bogota"
USE_I18N = True
USE_TZ = True

# --- Archivos estáticos y media
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # aquí caerá collectstatic

STATICFILES_DIRS = []
ktapp_static = BASE_DIR / "ktapp" / "static"
if ktapp_static.exists():
    STATICFILES_DIRS.append(ktapp_static)

project_static = BASE_DIR / "static"
if project_static.exists():
    STATICFILES_DIRS.append(project_static)

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Auth redirects
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "cartera:clientes_list"
LOGOUT_REDIRECT_URL = "login"

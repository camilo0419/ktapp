# ktapp/ktapp/settings.py — LOCAL (desarrollo)
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

# ---- Local por defecto
DEBUG = True
SECRET_KEY = "dev-secret-key-solo-local"
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "[::1]"]
PDF_ENGINE = "auto"

# CSRF confiando en orígenes locales
CSRF_TRUSTED_ORIGINS = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]

# ---- Apps
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Apps del proyecto
    "cartera",
]

# ---- Middleware
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "ktapp.urls"
WSGI_APPLICATION = "ktapp.wsgi.application"

# ---- Templates
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ---- Base de datos (SQLite local)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# ---- i18n
LANGUAGE_CODE = "es-co"
TIME_ZONE = "America/Bogota"
USE_I18N = True
USE_TZ = True

# ---- Static & Media (local)
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"   # para tests de collectstatic si quieres
STATICFILES_DIRS = []

# 1) estáticos del paquete del proyecto: ktapp/ktapp/static
ktapp_package_static = BASE_DIR / "ktapp" / "static"
if ktapp_package_static.exists():
    STATICFILES_DIRS.append(ktapp_package_static)

# 2) (opcional) carpeta 'static' a nivel proyecto
project_static = BASE_DIR / "static"
if project_static.exists():
    STATICFILES_DIRS.append(project_static)

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ---- Seguridad (OFF en local)
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
# SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # no usar en local

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---- Login/Logout
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "cartera:clientes_list"
LOGOUT_REDIRECT_URL = "login"

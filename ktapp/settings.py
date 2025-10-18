from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Básicos
SECRET_KEY = "dev-secret-key-cambia-esto"
DEBUG = True
ALLOWED_HOSTS = []  # en producción agrega tu dominio o IP

# --- Apps
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "cartera",          # tu app
    # OJO: no agregues "ktapp" aquí; es el proyecto, no una app
]

# --- Middleware
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

# --- Templates
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],  # si usas templates globales
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

WSGI_APPLICATION = "ktapp.wsgi.application"

# --- Base de datos (dev)
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
STATIC_ROOT = BASE_DIR / "staticfiles"

# Incluimos rutas de estáticos que no vienen de apps instaladas.
# Aquí es donde pusimos css, icons, manifest y sw: ktapp/static/ktapp/...
STATICFILES_DIRS = []

ktapp_static = BASE_DIR / "ktapp" / "static"
if ktapp_static.exists():
    STATICFILES_DIRS.append(ktapp_static)

# (Opcional) Si además tienes una carpeta raíz /static/
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

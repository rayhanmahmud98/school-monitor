"""
Django settings for school_monitor.

LOCAL DEVELOPMENT ONLY: DEBUG=True, SQLite, insecure secret key.
Do not deploy this configuration to production.
"""
from pathlib import Path

# CHANGED: BASE_DIR was .parent.parent (one level too high).
# settings.py now lives directly next to manage.py, so BASE_DIR must be its own folder.
BASE_DIR = Path(__file__).resolve().parent

SECRET_KEY = "django-insecure-local-development-key-do-not-use-in-production"
DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Project apps
    "accounts",
    "students",
    "academics",
    "dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Logs every successful write request to AuditLog (must come after auth)
    "academics.middleware.AuditLogMiddleware",
]

# CHANGED: was "school_monitor.urls". urls.py is now top-level, next to this file.
ROOT_URLCONF = "urls"

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
                # Adds `role` and `base_template` (base_admin/teacher/parent.html)
                "accounts.context_processors.role_context",
            ],
        },
    },
]

# CHANGED: was "school_monitor.wsgi.application". wsgi.py is now top-level.
WSGI_APPLICATION = "wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:home"   # home view redirects by role
LOGOUT_REDIRECT_URL = "accounts:login"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Dhaka"  # change to your local zone; "today" for attendance uses this
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
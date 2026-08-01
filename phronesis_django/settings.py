# ==============================================================================
# File: phronesis_django/settings.py
# Description: Configuration settings for the Phronesis Django application
# Component: Core / Settings
# Version: 1.1 (Gold Master)
# Created: 2026-06-26
# Last Update: 2026-07-31
# ==============================================================================
import os
import sys
from pathlib import Path

import dj_database_url

from phronesis_django.data_paths import (
    default_database_url,
    get_phronesis_data_dir,
    load_runtime_dotenv,
)

BASE_DIR = Path(__file__).resolve().parent.parent

# VN-B01 — standalone must not inherit checkout DATABASE_URL (see load_runtime_dotenv).
_data_dir = get_phronesis_data_dir()
load_runtime_dotenv(base_dir=BASE_DIR, data_dir=_data_dir)

# Security: Keep this safe!
SECRET_KEY = os.environ["SECRET_KEY"]
DEBUG = os.environ.get("DEBUG", "False") == "True"
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]


# Security headers and cookie hardening
# Standalone Waitress is HTTP on loopback — never require Secure cookies there.
_standalone_http = _data_dir is not None or os.environ.get("PHRONESIS_STANDALONE", "") == "1"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = (not DEBUG) and (not _standalone_http)
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = (not DEBUG) and (not _standalone_http)
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_htmx",
    "axes",
    "phronesis_app.apps.PhronesisAppConfig",
]

if "test" in sys.argv:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db_test.sqlite3",
        }
    }
else:
    _db_url = (os.environ.get("DATABASE_URL") or "").strip()
    if not _db_url:
        _db_url = default_database_url(base_dir=BASE_DIR, data_dir=_data_dir)
    DATABASES = {
        "default": dj_database_url.config(
            default=_db_url,
            conn_max_age=600,
        )
    }

# HTMX Middleware is required for that "Reflex-like" interactivity
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    # VN-E04 / S-53 — after AuthenticationMiddleware (django-axes requirement)
    "axes.middleware.AxesMiddleware",
    "phronesis_app.middleware.OwnerOnlyAccessMiddleware",
]

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
                "phronesis_app.context_processors.global_settings",
            ],
        },
    },
]

# Static files (CSS, JavaScript, Images)
# Production (Railway/Railpack, Compose image): run collectstatic so WhiteNoise
# can serve from STATIC_ROOT. Finders-only path is for local/standalone DEBUG.
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        # Compressed (not Manifest) — avoids hard 500s if a hashed ref is missing.
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}
# Waitress + DEBUG=False still needs app static (favicon, themes.css) without
# a prior collectstatic when running the standalone launcher.
if DEBUG or _standalone_http:
    WHITENOISE_USE_FINDERS = True
    WHITENOISE_AUTOREFRESH = True

ROOT_URLCONF = "phronesis_django.urls"

# Password hashing algorithms (FR-SEC-002)
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

# Auth redirection parameters
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "login"

# VN-E04 / S-53 — brute-force lockout on owner login (django-axes)
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]
AXES_FAILURE_LIMIT = int(os.environ.get("AXES_FAILURE_LIMIT", "5"))
# Cooloff in hours (float OK); unset AXES_COOLOFF_HOURS for hard lock until reset
_axes_cooloff = (os.environ.get("AXES_COOLOFF_HOURS") or "1").strip()
AXES_COOLOFF_TIME = float(_axes_cooloff) if _axes_cooloff else None
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_VERBOSE = False
AXES_LOCKOUT_TEMPLATE = "registration/lockout.html"
AXES_HTTP_RESPONSE_CODE = 429
# Trust X-Forwarded-For when behind Railway / reverse proxies (matches SECURE_PROXY_SSL_HEADER)
AXES_IPWARE_META_PRECEDENCE_ORDER = (
    "HTTP_X_FORWARDED_FOR",
    "REMOTE_ADDR",
)
# Django test Client.login() has no request; keep axes off in the suite except lockout tests.
if "test" in sys.argv:
    AXES_ENABLED = False


# Internationalization and Timezones
TIME_ZONE = "UTC"
USE_TZ = True
USE_I18N = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Email Configuration (SMTP with Local Console Fallback)
EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", 587))
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "True") == "True"
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "webmaster@localhost")

# Fallback to console backend in development if SMTP credentials are not configured
if not EMAIL_HOST_USER or not EMAIL_HOST_PASSWORD:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Google Calendar OAuth (ENG-CAL) — optional until Settings round
GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
GOOGLE_OAUTH_REDIRECT_URI = os.environ.get(
    "GOOGLE_OAUTH_REDIRECT_URI",
    "http://127.0.0.1:8000/calendar/oauth2callback/",
)

# Microsoft Graph calendar OAuth (ENG-CAL-MS)
MICROSOFT_OAUTH_CLIENT_ID = os.environ.get("MICROSOFT_OAUTH_CLIENT_ID", "")
MICROSOFT_OAUTH_CLIENT_SECRET = os.environ.get("MICROSOFT_OAUTH_CLIENT_SECRET", "")
MICROSOFT_OAUTH_REDIRECT_URI = os.environ.get("MICROSOFT_OAUTH_REDIRECT_URI", "")

# ---------------------------------------------------------------------------
# Celery Beat / worker (P5-04) — reminder sweep + telemetry warm
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_ALWAYS_EAGER = (
    os.environ.get("CELERY_TASK_ALWAYS_EAGER", "False") == "True" or "test" in sys.argv
)
CELERY_TASK_EAGER_PROPAGATES = True

from celery.schedules import crontab  # noqa: E402 — after TIME_ZONE

CELERY_BEAT_SCHEDULE = {
    "sweep-reminders-every-2-minutes": {
        "task": "phronesis_app.sweep_reminders",
        "schedule": 120.0,
    },
    "warm-telemetry-every-15-minutes": {
        "task": "phronesis_app.warm_telemetry",
        "schedule": 900.0,
    },
    "compute-stability-daily": {
        "task": "phronesis_app.compute_stability",
        "schedule": crontab(hour=12, minute=5),
    },
}

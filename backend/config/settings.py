"""
SecureVault Django settings.

All configuration comes from environment variables (see .env.example).
A local .env at the repository root is loaded when present; in Docker the
variables come from docker-compose. There are no secret defaults: the app
refuses to start without DJANGO_SECRET_KEY and POSTGRES_PASSWORD.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

from core.logs import logging_config

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent

# Real environment variables always win over the .env file. SV_ENV_FILE points somewhere else (tests use an empty
# file so the developer's .env cannot fill in a variable that a test deliberately leaves unset).
load_dotenv(os.environ.get("SV_ENV_FILE") or REPO_ROOT / ".env", override=False)


def env(name: str, default: str | None = None, *, required: bool = False) -> str:
    value = os.environ.get(name, default)
    if required and not value:
        raise ImproperlyConfigured(f"Environment variable {name} is required.")
    return value or ""


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = env("DJANGO_SECRET_KEY", required=True)
if not DEBUG and (SECRET_KEY == "change-me" or len(SECRET_KEY) < 50):  # noqa: S105 - rejects the placeholder
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be a strong random value in production.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "daphne",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "channels",
    "core",
    "apps.organizations",
    "apps.accounts",
    "apps.departments",
    "apps.services_catalog",
    "apps.policies",
    "apps.audit",
    "apps.vault",
    "apps.notifications",
    "apps.sharing",
    "apps.access_requests",
    # Order matters: each app registers its zero-trust gate check in ready(), in pipeline order.
    "apps.devices",  # device trust (6), anomaly policy (7)
    "apps.lockdown",  # lockdown (8)
    "apps.imports",
    "apps.reports",
]

MIDDLEWARE = [
    "core.request_context.RequestContextMiddleware",
    "core.observability.ObservabilityMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
ASGI_APPLICATION = "config.asgi.application"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
            ],
        },
    },
]

# --- Database (PostgreSQL only; concurrency guarantees depend on it) ---
# CONN_MAX_AGE is 0 (close the connection after each request) in every mode. Django advises against persistent
# connections under ASGI, and the development stack showed why: with CONN_MAX_AGE=60 under Daphne, idle connections
# (each last used by a health check) piled up at roughly one every minute and were never reused. Production avoids
# the per-request connect cost with psycopg's connection pool (Django 5.1+) instead.
DB_POOL = env_bool("SV_DB_POOL", not DEBUG)
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "securevault"),
        "USER": env("POSTGRES_USER", "securevault"),
        "PASSWORD": env("POSTGRES_PASSWORD", required=True),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 0,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {"connect_timeout": 5},
    }
}
if DB_POOL:
    DATABASES["default"]["OPTIONS"]["pool"] = {
        "min_size": int(env("SV_DB_POOL_MIN", "2")),
        "max_size": int(env("SV_DB_POOL_MAX", "10")),
        "timeout": float(env("SV_DB_POOL_TIMEOUT", "10")),  # seconds to wait for a free connection before failing
        "max_lifetime": 30 * 60,
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

# --- Redis / Channels ---
REDIS_URL = env("REDIS_URL", "redis://localhost:6379/0")
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}

# --- Passwords: Argon2id first; others only to verify legacy hashes ---
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Sessions & cookies (server-side sessions, revocable by deleting rows) ---
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_NAME = "sv_session"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"  # the SPA and the API share an origin, so no cross-site request needs the cookie
SESSION_COOKIE_AGE = 60 * 60 * 8  # 8-hour absolute lifetime
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
CSRF_COOKIE_NAME = "sv_csrftoken"
CSRF_COOKIE_HTTPONLY = False  # SPA reads it to send X-CSRFToken; it is not a secret on its own
CSRF_COOKIE_SAMESITE = "Strict"

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    # Orchestrator probes and the metrics scraper reach the app over the private network without TLS.
    SECURE_REDIRECT_EXEMPT = [r"^api/v1/health/$", r"^api/v1/metrics/$"]
    # security.W021 asks for HSTS preloading. That commits the whole domain to browsers' preload lists for months,
    # so it is a decision for the domain owner (see docs/deployment-guide.md), not a default.
    SILENCED_SYSTEM_CHECKS = ["security.W021"]

# --- Upload limits (Excel imports are validated again in the import app) ---
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# --- REST framework ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["core.authentication.SessionAuthentication"],
    # JSON only: no browsable API (an HTML form surface) and no form-encoded bodies. Upload views opt in to multipart.
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    # Secure default: every endpoint requires an ACTIVE user in an ACTIVE organization
    # unless a view explicitly opts out.
    "DEFAULT_PERMISSION_CLASSES": ["core.permissions.IsActiveMember"],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "core.pagination.StandardPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "core.exceptions.api_exception_handler",
    # `?format=` is ours (report exports), not DRF's renderer override.
    "URL_FORMAT_OVERRIDE": None,
    # These fail open if Redis is unreachable; credential entry points use StrictScopedRateThrottle and fail closed.
    "DEFAULT_THROTTLE_CLASSES": [
        "core.throttling.AnonRateThrottle",
        "core.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "60/min",
        "user": "600/min",
        "login": "10/min",
        "invitation_accept": "10/min",
        "password_reset": "5/min",
        "reveal": "30/min",  # per user: slows bulk secret exfiltration through a hijacked session
    },
    # 0 = use REMOTE_ADDR and ignore X-Forwarded-For (which clients can forge).
    # Set to the number of trusted reverse proxies in production.
    "NUM_PROXIES": int(env("DJANGO_NUM_PROXIES", "0")),
}

# --- Account security ---
FRONTEND_URL = env("FRONTEND_URL", "http://localhost:5173").rstrip("/")
INVITATION_TTL_HOURS = int(env("INVITATION_TTL_HOURS", "72"))
LOGIN_LOCKOUT_THRESHOLD = 5  # failed attempts per email ...
LOGIN_LOCKOUT_SECONDS = 15 * 60  # ... within / locked for this window
PASSWORD_RESET_TTL_MINUTES = 30

# --- Encryption keys (see core/crypto.py). Each purpose has its own keyring; they must not overlap. ---
MFA_ENCRYPTION_KEYS = env("SV_MFA_ENCRYPTION_KEYS", required=True)
VAULT_KEY_PROVIDER = env("SV_VAULT_KEY_PROVIDER", "apps.vault.keys.EnvKeyProvider")
VAULT_KEK_KEYS = env("SV_VAULT_KEK_KEYS", required=True)  # wraps per-organization data keys
VAULT_BLIND_INDEX_KEYS = env("SV_BLIND_INDEX_KEYS", required=True)  # HMAC key for reuse detection only
VAULT_ARCHIVE_RETENTION_DAYS = 30  # archived items may be purged permanently after this long

# --- Employee imports ---
IMPORT_MAX_BYTES = 2 * 1024 * 1024
IMPORT_MAX_ROWS = 5_000
IMPORT_SYNC_ROW_LIMIT = 200  # larger files are queued for `manage.py run_worker`

# --- Reports ---
REPORT_EXPORT_MAX_ROWS = 10_000  # per export file; larger results must be narrowed by filters

# --- Email (password reset). Dev default writes .eml files to backend/var/mail, never to logs. ---
EMAIL_BACKEND = env("DJANGO_EMAIL_BACKEND", "django.core.mail.backends.filebased.EmailBackend")
EMAIL_FILE_PATH = BASE_DIR / "var" / "mail"
EMAIL_HOST = env("DJANGO_EMAIL_HOST", "localhost")
EMAIL_PORT = int(env("DJANGO_EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("DJANGO_EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("DJANGO_EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("DJANGO_EMAIL_USE_TLS", True)
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = env("DJANGO_DEFAULT_FROM_EMAIL", "SecureVault <no-reply@securevault.local>")

# --- API documentation and operations endpoints ---
ENABLE_API_DOCS = env_bool("SV_ENABLE_API_DOCS", DEBUG)  # /api/v1/schema/ and /api/v1/docs/ (404 when off)
METRICS_TOKEN = env("SV_METRICS_TOKEN", "")  # bearer token for /api/v1/metrics/; empty = endpoint disabled
if METRICS_TOKEN and len(METRICS_TOKEN) < 32:
    raise ImproperlyConfigured("SV_METRICS_TOKEN must be at least 32 characters (or unset to disable metrics).")

SPECTACULAR_SETTINGS = {
    "TITLE": "SecureVault API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SERVE_PERMISSIONS": ["core.permissions.ApiDocsEnabled", "rest_framework.permissions.IsAuthenticated"],
    "ENUM_NAME_OVERRIDES": {
        "UserStatusEnum": "apps.accounts.models.User.Status",
        "DepartmentStatusEnum": "apps.departments.models.Department.Status",
        "ServiceStatusEnum": "apps.services_catalog.models.ServiceCatalog.Status",
        "SharePermissionEnum": "apps.sharing.models.Share.Permission",
        "RequestPermissionEnum": "apps.access_requests.models.AccessRequest.Permission",
    },
}

# --- Cache (Redis; never used for decrypted secrets) ---
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# --- Logging: one JSON object per line in production (see core/logs.py); never request bodies or secrets ---
LOG_JSON = env_bool("SV_LOG_JSON", not DEBUG)
LOGGING = logging_config(json_output=LOG_JSON, level=env("SV_LOG_LEVEL", "INFO").upper())

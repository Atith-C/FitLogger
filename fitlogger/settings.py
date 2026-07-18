"""
Django settings for the Fit Logger project.

All sensitive and environment-specific configuration is read from environment
variables (loaded from a local .env file in development). Nothing secret is
committed to source control.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load the local .env file if present. In production the process environment
# supplies these values instead and load_dotenv() is a harmless no-op.
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    """Read a boolean from the environment, accepting the usual truthy spellings."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    """Read a comma-separated environment variable into a list of trimmed strings."""
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


# --------------------------------------------------------------------------
# Core security
# --------------------------------------------------------------------------

# No fallback default: an unset secret key must fail loudly rather than
# silently ship a predictable key.
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

DEBUG = env_bool("DJANGO_DEBUG", default=False)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

# Needed so the PWA and fetch() calls from the browser pass CSRF origin checks.
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")


# --------------------------------------------------------------------------
# Applications
# --------------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Fit Logger domain applications
    "users",
    "workouts",
    "analytics",
    "ai_planner",
    "assistant",
    "adminportal",
    "notifications",
    "messaging",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "fitlogger.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "fitlogger.context_processors.navigation",
            ],
        },
    },
]

WSGI_APPLICATION = "fitlogger.wsgi.application"
ASGI_APPLICATION = "fitlogger.asgi.application"


# --------------------------------------------------------------------------
# Database — PostgreSQL
# --------------------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DATABASE_NAME", "fitlogger"),
        "USER": os.environ.get("DATABASE_USER", "postgres"),
        "PASSWORD": os.environ.get("DATABASE_PASSWORD", ""),
        "HOST": os.environ.get("DATABASE_HOST", "localhost"),
        "PORT": os.environ.get("DATABASE_PORT", "5432"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "users:login"
LOGIN_REDIRECT_URL = "workouts:home"
LOGOUT_REDIRECT_URL = "users:login"

# The session cookie is dropped when the browser closes, rather than persisting
# for Django's default 14 days. Chosen deliberately: closing the browser should
# end the session. Mobile browsers keep their process alive in the background,
# so locking the phone between sets does not log the user out.
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# Any activity refreshes the session, so a long workout cannot time out
# mid-session while the user is actively logging sets.
SESSION_SAVE_EVERY_REQUEST = True


# --------------------------------------------------------------------------
# Internationalization
# --------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("DJANGO_TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True


# --------------------------------------------------------------------------
# Static files
# --------------------------------------------------------------------------

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"


# --------------------------------------------------------------------------
# AI planner
# --------------------------------------------------------------------------

# DEVIATION FROM SPEC: the specification names the Anthropic Claude API. The
# project owner supplied an OpenAI key instead, so ai_planner uses the OpenAI
# SDK. The AI provider is confined to ai_planner/services.py — nothing else in
# the codebase knows or cares which model produced a plan.
#
# Read at call time by ai_planner.services. Never exposed to templates or JS.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
# Embedding model for the Joey assistant's RAG retrieval.
OPENAI_EMBEDDING_MODEL = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

# How long to wait on the AI provider before giving up, in seconds.
AI_REQUEST_TIMEOUT_SECONDS = int(os.environ.get("AI_REQUEST_TIMEOUT_SECONDS", "60"))


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "{levelname} {asctime} {name} — {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        # Application loggers. Technical failures (AI errors, sync errors) are
        # logged here; users only ever see friendly messages.
        "fitlogger": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "ai_planner": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "workouts": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "analytics": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}


# --------------------------------------------------------------------------
# Production-only hardening (enabled automatically when DEBUG is off)
# --------------------------------------------------------------------------

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True

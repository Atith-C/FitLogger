"""Test settings — run the suite against a local PostgreSQL, never Neon.

The project's .env points DATABASE_* at production Neon, so a plain
`manage.py test` would create and drop a test database on the live instance.
This module redirects the test runner at a local PostgreSQL instead, reading
its credentials from LOCAL_DATABASE_* so no password is ever committed.

Usage:
    python manage.py test --settings=fitlogger.settings_test

Django creates and drops `test_<NAME>`, so the local `fitlogger` database is
never touched either.
"""

import os

from .settings import *  # noqa: F401,F403
from .settings import DATABASES

DATABASES["default"] = {
    **DATABASES["default"],
    "NAME": os.environ.get("LOCAL_DATABASE_NAME", "fitlogger"),
    "USER": os.environ.get("LOCAL_DATABASE_USER", "postgres"),
    "PASSWORD": os.environ.get("LOCAL_DATABASE_PASSWORD", ""),
    "HOST": os.environ.get("LOCAL_DATABASE_HOST", "localhost"),
    "PORT": os.environ.get("LOCAL_DATABASE_PORT", "5432"),
    # A locally built PostgreSQL usually has no SSL support at all.
    "OPTIONS": {"sslmode": os.environ.get("LOCAL_DATABASE_SSLMODE", "disable")},
}

# Tests must never reach Brevo. Kept here as well as in the phase 1 settings so
# it holds regardless of how DEBUG is set when the suite runs.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

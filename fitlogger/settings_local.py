"""Development settings — run the app against a local PostgreSQL, not Neon.

The project's .env points DATABASE_* at production Neon, so `manage.py
runserver` with the default settings serves the live database: every account
created while clicking around, every password reset, every test workout lands
in real user data.

This module points the same app at the local copy instead, reading its
credentials from LOCAL_DATABASE_* so no password is committed.

Usage:
    python manage.py runserver --settings=fitlogger.settings_local
    python manage.py migrate --settings=fitlogger.settings_local
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

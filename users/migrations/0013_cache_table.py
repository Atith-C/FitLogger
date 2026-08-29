"""Create the database cache table that holds the rate-limit counters.

Django normally expects `manage.py createcachetable` to be run by hand. That
would be a step someone has to remember on every fresh environment, and
forgetting it takes down every page that touches the cache — which, once rate
limiting is in place, means signup and password recovery. Doing it in a
migration ties it to `migrate`, which the deploy runs anyway.
"""

from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    # Idempotent: the command reports and skips a table that already exists.
    call_command("createcachetable", "fitlogger_cache", verbosity=0)


def drop_cache_table(apps, schema_editor):
    # Only cache entries live here, so dropping it loses nothing but counters.
    schema_editor.execute("DROP TABLE IF EXISTS fitlogger_cache")


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0012_grandfather_existing_accounts"),
    ]

    operations = [
        migrations.RunPython(create_cache_table, drop_cache_table),
    ]

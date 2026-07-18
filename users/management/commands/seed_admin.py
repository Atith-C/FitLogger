"""Create (or update) the single Admin account.

    python manage.py seed_admin

The password is read from the ADMIN_PASSWORD environment variable (set it in
.env) and hashed by Django's set_password — it is never hardcoded or stored in
plain text. Name and email default to the project's admin, and can be
overridden with --email / --name / --username.

Safe to re-run: it updates the existing admin (e.g. to reset the password or
re-grant the role) rather than creating duplicates.
"""

import os

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from users.models import Role
from users.services import get_or_create_profile

DEFAULT_NAME = "Atith Chandran"
DEFAULT_EMAIL = "adithchandran2003@gmail.com"
DEFAULT_USERNAME = "atith"


class Command(BaseCommand):
    help = "Create or update the platform Admin account (role=ADMIN)."

    def add_arguments(self, parser):
        parser.add_argument("--email", default=DEFAULT_EMAIL)
        parser.add_argument("--name", default=DEFAULT_NAME)
        parser.add_argument("--username", default=DEFAULT_USERNAME)

    @transaction.atomic
    def handle(self, *args, **options):
        password = os.environ.get("ADMIN_PASSWORD", "").strip()
        if not password:
            raise CommandError(
                "ADMIN_PASSWORD is not set. Add it to your .env "
                "(e.g. ADMIN_PASSWORD=your-admin-password) and run again."
            )

        email = options["email"].strip()
        username = options["username"].strip()
        first, _, last = options["name"].partition(" ")

        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": email, "first_name": first, "last_name": last},
        )
        user.email = email
        user.first_name = first
        user.last_name = last
        user.is_staff = True  # allow access to Django's own /admin/ too
        user.set_password(password)  # hashed, never stored in plain text
        user.save()

        profile = get_or_create_profile(user)
        profile.role = Role.ADMIN
        profile.save(update_fields=["role"])

        action = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{action} admin account '{username}' ({email}) with role=ADMIN."
            )
        )

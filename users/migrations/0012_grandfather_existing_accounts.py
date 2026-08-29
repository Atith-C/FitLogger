"""Mark every account that predates email verification as verified.

The new field defaults to False, which is right for signups from here on: they
must follow the link mailed to them. Applied to accounts created before
verification existed, that same default would lock all of them out at once —
they were never sent a link, and some registered with addresses that are not
Gmail at all and so could never satisfy the new rule.

Only rows existing when this migration runs are touched, so later signups are
unaffected.
"""

from django.db import migrations


def grandfather_existing_accounts(apps, schema_editor):
    UserProfile = apps.get_model("users", "UserProfile")
    UserProfile.objects.update(email_verified=True)


def unverify_everyone(apps, schema_editor):
    """Reverse: put every account back to unverified.

    This is what the field looked like a moment before the forward migration,
    which is the only honest reversal available — nothing records which
    accounts were grandfathered and which verified for real.
    """
    UserProfile = apps.get_model("users", "UserProfile")
    UserProfile.objects.update(email_verified=False)


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0011_userprofile_email_verified"),
    ]

    operations = [
        migrations.RunPython(grandfather_existing_accounts, unverify_everyone),
    ]

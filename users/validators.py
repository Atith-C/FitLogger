"""Gmail-only signup rules.

Signup accepts Gmail addresses only. Whether a Gmail address actually *exists*
cannot be checked from here — Google accepts mail for every address at the SMTP
layer precisely to stop that kind of probing — so ownership is proved instead
by the user opening the mailbox and clicking the link we send there.
"""

from django import forms

# googlemail.com reaches the same mailbox as gmail.com: Google still delivers
# it, and some older accounts were created under that name.
GMAIL_DOMAINS = frozenset({"gmail.com", "googlemail.com"})


def normalize_gmail(email):
    """The canonical form of a Gmail address, for duplicate detection.

    Gmail ignores dots in the local part and discards everything from a "+"
    onwards, so "a.dith+gym@googlemail.com" and "adith@gmail.com" are one
    inbox. Without collapsing them, a single mailbox could register unlimited
    accounts that all look distinct.

    Returns "" for anything that is not a usable Gmail address, so a caller
    cannot accidentally compare two non-Gmail addresses as though they had
    been normalized.
    """
    local, _, domain = email.strip().lower().partition("@")
    if domain not in GMAIL_DOMAINS:
        return ""

    local = local.partition("+")[0].replace(".", "")
    return f"{local}@gmail.com" if local else ""


def validate_gmail(email):
    """Return the address lowercased, or raise if it is not usable Gmail."""
    email = email.strip().lower()

    if email.rpartition("@")[2] not in GMAIL_DOMAINS:
        raise forms.ValidationError(
            "Please use a Gmail address — Fit Logger sends your account "
            "verification and password resets there."
        )
    if not normalize_gmail(email):
        # A local part that is only dots, or empty before the "+", leaves
        # nothing to address the mail to.
        raise forms.ValidationError("Please enter a valid Gmail address.")

    return email


def gmail_already_registered(email):
    """Whether any account already owns this Gmail mailbox.

    Compared on the normalized form, so the dot and "+tag" spellings of one
    inbox cannot each claim their own account.
    """
    from django.contrib.auth.models import User

    target = normalize_gmail(email)
    if not target:
        return False

    # ponytail: compares candidates in Python, because the dots this strips
    # cannot be stripped in SQL. The filter narrows to Gmail-ish rows first,
    # which is enough at tens of users. If the table reaches thousands, store
    # the normalized address in its own column with a unique index.
    candidates = User.objects.filter(email__icontains="@g").values_list("email", flat=True)
    return any(normalize_gmail(existing) == target for existing in candidates)

"""Business logic for user registration and fitness profiles.

Views stay thin: they handle HTTP and delegate here.
"""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import BodyMeasurement, CalorieCalculation, Role, UserProfile


# --------------------------------------------------------------------------
# Notifying admins of trainee activity (Phase B)
# --------------------------------------------------------------------------

# (field, label) for profile changes worth telling an admin about. The labels
# are title-case because they are read inside a notification title —
# "Atith updated Weight".
_TRACKED_PROFILE_FIELDS = [
    ("goal", "Goal"),
    ("weight_kg", "Weight"),
    ("height_cm", "Height"),
    ("age", "Age"),
    ("sex", "Gender"),
    ("days_per_week", "Training Days"),
    ("experience_level", "Experience Level"),
    ("workout_location", "Workout Location"),
    ("session_duration", "Session Length"),
]


def trainee_display(user):
    """The trainee's name as an admin should see it."""
    return user.get_full_name() or user.username


def admin_trainee_link(trainee):
    """Where an admin notification about this trainee should open — the
    trainee's detail page in the admin portal."""
    from django.urls import reverse

    return reverse("adminportal:trainee_detail", args=[trainee.id])


def _profile_value(profile, field):
    """A tracked field's value as an admin should read it.

    Choice fields render their label ("Build muscle"), not their stored key
    ("BUILD_MUSCLE"). Decimals are pinned to one place: the old value is read
    back from the database while the new one comes straight off the form, so
    without this a weigh-in of "72" would read "70.0 → 72".
    """
    getter = getattr(profile, f"get_{field}_display", None)
    value = getter() if callable(getter) else getattr(profile, field)

    if value is None or value == "":
        return "—"
    if isinstance(value, Decimal):
        return f"{value:.1f}"
    return value


def _notify_profile_change(new_profile, old_profile):
    """Tell admins when a trainee changes tracked profile fields."""
    if old_profile is None or not new_profile.is_trainee:
        return

    changed = [
        (field, label)
        for field, label in _TRACKED_PROFILE_FIELDS
        if getattr(old_profile, field) != getattr(new_profile, field)
    ]
    if not changed:
        return

    from notifications.models import Category
    from notifications.services import notify_admins

    user = new_profile.user
    name = trainee_display(user)
    labels = [label for _, label in changed]
    goal_changed = "Goal" in labels

    if len(changed) == 1:
        # Name the field, per the spec's "Atith updated Weight". Goal takes a
        # different verb there: "Riya changed Goal".
        field, label = changed[0]
        title = f"{name} changed Goal" if goal_changed else f"{name} updated {label}"
        message = (
            f"{_profile_value(old_profile, field)} → "
            f"{_profile_value(new_profile, field)}"
        )
    else:
        # The profile form saves every field at once, so a notification per
        # field would be noise. Group them into one.
        title = f"{name} updated their profile"
        message = f"Updated: {', '.join(labels)}."

    notify_admins(
        title,
        message=message,
        link=admin_trainee_link(user),
        actor=user,
        category=Category.GOAL if goal_changed else Category.PROFILE,
    )


@transaction.atomic
def register_user(form):
    """Create a user from a validated RegistrationForm, with their profile.

    Public signup always produces a TRAINEE — the role is set here on the
    server, never taken from the request. The user and their profile are
    created together in one transaction, so a user can never exist without one.
    """
    user = form.save()
    UserProfile.objects.create(user=user, role=Role.TRAINEE)

    from notifications.models import Category
    from notifications.services import notify_admins

    notify_admins(
        # The spec's exact string. The name lives in the message rather than
        # the title, so the list still says who without breaking the wording.
        "New Trainee Registered",
        message=f"{trainee_display(user)} just created an account.",
        link=admin_trainee_link(user),
        actor=user,
        category=Category.NEW_TRAINEE,
    )
    return user


def get_or_create_profile(user):
    """Return the user's profile, creating a default one if it is missing.

    Registration always creates a profile, but users made with
    createsuperuser bypass that path — so we heal the gap here rather than
    crashing on a missing related object.
    """
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile


def update_profile(form):
    """Persist a validated UserProfileForm, notifying admins of any change.

    The DB copy is read before saving so we can diff old vs new — form.instance
    already holds the new values by the time is_valid() has run.
    """
    old_profile = UserProfile.objects.filter(pk=form.instance.pk).first()
    saved = form.save()
    _notify_profile_change(saved, old_profile)
    return saved


# --------------------------------------------------------------------------
# Profile sharing permission (Phase D)
# --------------------------------------------------------------------------


def set_profile_sharing(trainee, enabled):
    """Enable/disable the trainee sharing their profile with admins.

    Notifies admins only when the value actually changes. Returns the profile.
    """
    profile = get_or_create_profile(trainee)
    if profile.profile_shared == enabled:
        return profile  # no change, no notification

    profile.profile_shared = enabled
    profile.save(update_fields=["profile_shared"])

    from notifications.models import Category
    from notifications.services import notify_admins

    name = trainee_display(trainee)
    verb = "enabled" if enabled else "disabled"
    notify_admins(
        f"{name} {verb} Profile Sharing",
        message=f"You can{' now' if enabled else ' no longer'} view "
        f"{name}'s full profile.",
        link=admin_trainee_link(trainee),
        actor=trainee,
        category=Category.PERMISSION,
    )
    return profile


def can_admin_view_profile(trainee):
    """Whether admins may view this trainee's full profile (used in Phase G/H)."""
    return get_or_create_profile(trainee).profile_shared


# --------------------------------------------------------------------------
# Account state: blocking and soft deletion (Phase L)
# --------------------------------------------------------------------------


def set_trainee_blocked(trainee, blocked):
    """Block or unblock a trainee. No data is touched either way.

    Blocking is is_active=False, which Django's ModelBackend already refuses at
    login — and re-checks on every request, so a session opened before the
    block dies at the trainee's next click.
    """
    desired_active = not blocked
    if trainee.is_active == desired_active:
        return trainee  # already in that state

    trainee.is_active = desired_active
    trainee.save(update_fields=["is_active"])
    return trainee


@transaction.atomic
def soft_delete_trainee(trainee):
    """Remove a trainee's account while keeping every row they own.

    Deactivated as well as marked, so the same ModelBackend check that stops a
    blocked trainee logging in stops a removed one too.
    """
    profile = get_or_create_profile(trainee)
    if profile.is_deleted:
        return profile

    profile.deleted_at = timezone.now()
    profile.save(update_fields=["deleted_at"])

    trainee.is_active = False
    trainee.save(update_fields=["is_active"])
    return profile


@transaction.atomic
def restore_trainee(trainee):
    """Undo a soft delete, handing the account back intact."""
    profile = get_or_create_profile(trainee)
    if not profile.is_deleted:
        return profile

    profile.deleted_at = None
    profile.save(update_fields=["deleted_at"])

    trainee.is_active = True
    trainee.save(update_fields=["is_active"])
    return profile


def refused_login_reason(username, password):
    """Why a login was refused: "blocked", "removed", or None.

    authenticate() returns None for a blocked or removed account exactly as it
    does for a wrong password, so the real reason has to be worked out here.

    The password is checked first, deliberately: telling anyone who types a
    username that it is blocked would turn this into a username probe. Only
    someone who already proved the password learns why they are being kept out.
    """
    from django.contrib.auth.models import User

    user = User.objects.filter(username=username).first()
    if user is None or user.is_active or not user.check_password(password):
        return None

    return "removed" if get_or_create_profile(user).is_deleted else "blocked"


# --------------------------------------------------------------------------
# Body measurements (Wellness passport)
# --------------------------------------------------------------------------


def log_body_measurement(user, form):
    """Save a weigh-in for the user, replacing any entry on the same date.

    Ownership is set from the passed user, never from submitted data. The
    update-or-create keys on (user, date) so a second weigh-in on the same day
    corrects the first instead of creating a duplicate.
    """
    data = form.cleaned_data
    measurement, _ = BodyMeasurement.objects.update_or_create(
        user=user,
        recorded_on=data["recorded_on"],
        defaults={
            "weight_kg": data["weight_kg"],
            "body_fat_percentage": data.get("body_fat_percentage"),
            "muscle_mass_kg": data.get("muscle_mass_kg"),
            "notes": data.get("notes", ""),
        },
    )

    if get_or_create_profile(user).is_trainee:
        from notifications.models import Category
        from notifications.services import notify_admins

        notify_admins(
            f"{trainee_display(user)} logged a body measurement",
            message=f"Weight {measurement.weight_kg} kg on "
            f"{measurement.recorded_on:%d %b %Y}.",
            link=admin_trainee_link(user),
            actor=user,
            category=Category.BODY,
        )
    return measurement


def get_measurement_history(user):
    """This user's measurements, oldest first (chart order)."""
    return BodyMeasurement.objects.filter(user=user).order_by("recorded_on")


def get_latest_measurement(user):
    """The user's most recent measurement, or None."""
    return BodyMeasurement.objects.filter(user=user).order_by("-recorded_on").first()


# --------------------------------------------------------------------------
# Calorie calculation (persistence only; the maths lives in analytics)
# --------------------------------------------------------------------------


def get_calorie_calculation(user):
    """The user's saved calorie calculation, or None."""
    return CalorieCalculation.objects.filter(user=user).first()


def save_calorie_calculation(user, form, bmr, maintenance_calories):
    """Store (or overwrite) the user's calorie calculation.

    The form supplies the validated inputs; bmr and maintenance are computed by
    the analytics layer and passed in, so this function stays free of the maths.
    A user keeps a single current calculation, so update_or_create overwrites.
    """
    data = form.cleaned_data
    calculation, _ = CalorieCalculation.objects.update_or_create(
        user=user,
        defaults={
            "sex": data["sex"],
            "activity_level": data["activity_level"],
            "age": data["age"],
            "height_cm": data["height_cm"],
            "weight_kg": data["weight_kg"],
            "bmr": bmr,
            "maintenance_calories": maintenance_calories,
        },
    )

    if get_or_create_profile(user).is_trainee:
        from notifications.models import Category
        from notifications.services import notify_admins

        notify_admins(
            f"{trainee_display(user)} updated Maintenance Calories",
            message=f"Now {maintenance_calories} kcal/day (BMR {bmr}).",
            link=admin_trainee_link(user),
            actor=user,
            category=Category.CALORIES,
        )
    return calculation

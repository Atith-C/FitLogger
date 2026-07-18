from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .decorators import trainee_required
from .forms import RegistrationForm, UserProfileForm
from .models import Role
from .services import (
    get_or_create_profile,
    refused_login_reason,
    register_user,
    set_profile_sharing,
    update_profile,
)


def dashboard_url_for(user):
    """Where a user lands after login: admins to the portal, trainees home."""
    if get_or_create_profile(user).role == Role.ADMIN:
        return "adminportal:dashboard"
    return "workouts:home"


def login_view(request):
    """Login with a Trainee / Admin option.

    The chosen option must match the account's real role, so a trainee cannot
    sign in through the Admin option (or vice versa). The role itself always
    comes from the database, never from the form.
    """
    if request.user.is_authenticated:
        return redirect(dashboard_url_for(request.user))

    # "trainee" (default) or "admin" — purely which option the user picked.
    chosen = request.POST.get("as_role") or request.GET.get("as", "trainee")
    chosen = "admin" if chosen == "admin" else "trainee"

    username = ""
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)

        if user is None:
            # A blocked or removed account fails authenticate() exactly like a
            # wrong password, so say which — but only to someone whose password
            # was right. See refused_login_reason().
            reason = refused_login_reason(username, password)
            if reason == "blocked":
                messages.error(
                    request,
                    "Your account has been blocked. Please contact your coach.",
                )
            elif reason == "removed":
                messages.error(request, "This account has been removed.")
            else:
                messages.error(request, "Incorrect username or password.")
        else:
            role = get_or_create_profile(user).role
            wants_admin = chosen == "admin"
            is_admin = role == Role.ADMIN
            if wants_admin != is_admin:
                # Right credentials, wrong door.
                messages.error(
                    request,
                    "This is an admin account — use ‘Login as Admin’."
                    if is_admin
                    else "This is a trainee account — use ‘Login as Trainee’.",
                )
            else:
                login(request, user)
                return redirect(dashboard_url_for(user))

    return render(
        request, "users/login.html", {"as_role": chosen, "username": username}
    )


def register(request):
    """Create a TRAINEE account, its profile, and log the new user straight in.

    There is deliberately no way to register as an admin here — the role is
    fixed to TRAINEE in register_user().
    """
    if request.user.is_authenticated:
        return redirect(dashboard_url_for(request.user))

    # Platform signups switch. When an admin has closed registration, no account
    # is created on any path — GET shows the notice, POST is refused — so the
    # gate cannot be bypassed by posting straight to this URL.
    from .models import PlatformSettings

    if not PlatformSettings.load().signups_enabled:
        return render(request, "users/register.html", {"signups_closed": True})

    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = register_user(form)
            login(request, user)
            messages.success(request, "Welcome to Fit Logger. Set up your profile below.")
            return redirect("users:profile")
    else:
        form = RegistrationForm()

    return render(request, "users/register.html", {"form": form})


@login_required
def profile(request):
    """View and edit the fitness profile of the logged-in user.

    The profile is always resolved from request.user, never from a submitted
    id, so one user can never edit another's profile.
    """
    user_profile = get_or_create_profile(request.user)

    if request.method == "POST":
        form = UserProfileForm(request.POST, instance=user_profile)
        if form.is_valid():
            update_profile(form)
            messages.success(request, "Profile updated.")
            return redirect("users:profile")
    else:
        form = UserProfileForm(instance=user_profile)

    return render(request, "users/profile.html", {"form": form, "profile": user_profile})


@login_required
@trainee_required
@require_POST
def toggle_profile_sharing(request):
    """Enable or disable admin access to the trainee's profile.

    Acts only on request.user, so a trainee can only change their own sharing.
    Takes effect immediately and admins are notified of the change.
    """
    enabled = request.POST.get("share") == "on"
    set_profile_sharing(request.user, enabled)
    messages.success(
        request,
        "Admins can now view your profile."
        if enabled
        else "Your profile is now private.",
    )
    return redirect("users:profile")

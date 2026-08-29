from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from .decorators import trainee_required
from .recovery import ForgotAccountForm, send_password_changed_email
from .forms import RegistrationForm, UserProfileForm
from .models import Role
from .services import (
    get_or_create_profile,
    refused_login_reason,
    register_user,
    set_profile_sharing,
    update_profile,
    username_for_login,
)
from .verification import mark_verified, read_token, send_verification_email


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
        # What was typed, kept as-is so the form redisplays it unchanged.
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        # A forgotten username is the most common way in here, so the login box
        # accepts the Gmail address too.
        account = username_for_login(username)
        user = authenticate(request, username=account, password=password)

        if user is None:
            # A blocked or removed account fails authenticate() exactly like a
            # wrong password, so say which — but only to someone whose password
            # was right. See refused_login_reason().
            reason = refused_login_reason(account, password)
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
            profile = get_or_create_profile(user)
            role = profile.role
            wants_admin = chosen == "admin"
            is_admin = role == Role.ADMIN
            if not profile.email_verified:
                # Right password, but the mailbox was never opened. Say so
                # plainly — this is the one login refusal the user can fix
                # themselves, so it comes with the way to fix it.
                request.session["pending_verification_user_id"] = user.pk
                messages.error(
                    request,
                    "Confirm your email address before logging in. Check your "
                    "Gmail inbox (and spam folder) for the link we sent.",
                )
                return redirect("users:verify_sent")
            elif wants_admin != is_admin:
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
    """Create a TRAINEE account and mail it a verification link.

    The user is deliberately not logged in: the account is inert until the
    link in their inbox is followed, which is the only proof available that
    the Gmail address they typed is one they can actually open.

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
            # Remembered so the next page can name the address, and so a resend
            # needs no retyping. It identifies an unverified account only, and
            # grants nothing on its own.
            request.session["pending_verification_user_id"] = user.pk

            try:
                send_verification_email(user)
            except Exception:
                # The account exists but its link never went out. Saying
                # "check your inbox" here would leave them waiting for a
                # message that is not coming.
                messages.error(
                    request,
                    "Your account was created, but we could not send the "
                    "confirmation email. Please try again in a moment.",
                )
            return redirect("users:verify_sent")
    else:
        form = RegistrationForm()

    return render(request, "users/register.html", {"form": form})


def verify_sent(request):
    """"Check your inbox" — shown after signup, and after a refused login."""
    user = _pending_user(request)
    return render(request, "users/verify_sent.html", {"email": user.email if user else ""})


def verify_email(request, token):
    """Follow a verification link: activate the account and log the user in.

    Opening the link is the proof of ownership, so it is also enough to sign
    them in — they have just demonstrated control of the mailbox that the
    account's password can be reset through.
    """
    user = read_token(token)

    if user is None:
        # Forged, expired, or for an account since deleted. All the same to
        # the person holding it: they need a new link.
        return render(request, "users/verify_failed.html", status=400)

    if not user.is_active:
        # Blocked or removed while the link sat in their inbox. Verifying is
        # pointless and logging them in would undo an admin's decision.
        messages.error(request, "This account is no longer active.")
        return redirect("users:login")

    profile = get_or_create_profile(user)
    first_time = mark_verified(profile)

    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session.pop("pending_verification_user_id", None)

    if first_time:
        messages.success(request, "Email confirmed. Set up your profile below.")
        return redirect("users:profile")

    messages.success(request, "Email already confirmed — you are logged in.")
    return redirect(dashboard_url_for(user))


@require_POST
def resend_verification(request):
    """Send a fresh verification link to a pending signup.

    Acts only on the account already named by the session, so this cannot be
    pointed at someone else's address to mail them unprompted.
    """
    user = _pending_user(request)

    if user is None:
        messages.error(request, "Start again from the login page.")
        return redirect("users:login")

    try:
        send_verification_email(user)
    except Exception:
        messages.error(request, "We could not send the email. Please try again in a moment.")
    else:
        messages.success(request, f"A new link is on its way to {user.email}.")

    return redirect("users:verify_sent")


def _pending_user(request):
    """The unverified account this session is waiting on, if any."""
    from django.contrib.auth.models import User

    user_id = request.session.get("pending_verification_user_id")
    if not user_id:
        return None

    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None or get_or_create_profile(user).email_verified:
        return None
    return user


class ForgotAccountView(auth_views.PasswordResetView):
    """"I forgot my username, my password, or both" — one form for all three.

    The response is identical whether or not the address belongs to an account
    (Django's default), so this cannot be used to find out who is registered.
    """

    form_class = ForgotAccountForm
    template_name = "users/password_reset.html"
    subject_template_name = "users/emails/password_reset_subject.txt"
    email_template_name = "users/emails/password_reset.txt"
    html_email_template_name = "users/emails/password_reset.html"
    success_url = reverse_lazy("users:password_reset_done")
    extra_email_context = {"expiry_hours": settings.PASSWORD_RESET_TIMEOUT // 3600}


class SetNewPasswordView(auth_views.PasswordResetConfirmView):
    """Set a new password from a reset link."""

    template_name = "users/password_reset_confirm.html"
    success_url = reverse_lazy("users:password_reset_complete")

    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.user

        # Reaching here means they opened the mailbox, which is the same proof
        # signup verification asks for. Someone who never confirmed but can
        # still reset through that inbox has demonstrated it either way.
        mark_verified(get_or_create_profile(user))

        try:
            send_password_changed_email(user)
        except Exception:
            # The password is already saved. Failing the request now would
            # tell the user their reset did not work when it did, and they
            # would try again with a token that is already spent.
            pass

        return response


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

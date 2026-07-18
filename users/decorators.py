"""Role-based access control.

Enforcement is entirely server-side: these decorators read the user's role from
their profile, never from anything the client sends.
"""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from .models import Role
from .services import get_or_create_profile


def get_role(user):
    """The user's role, or None if not authenticated."""
    if not user.is_authenticated:
        return None
    return get_or_create_profile(user).role


def admin_required(view_func):
    """Allow only ADMIN users. Anonymous users are sent to login; a signed-in
    trainee gets a 403 (they are authenticated, just not authorised)."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if get_role(request.user) != Role.ADMIN:
            raise PermissionDenied("Admin access only.")
        return view_func(request, *args, **kwargs)

    return wrapper


def trainee_required(view_func):
    """Allow only TRAINEE users. Admins are authenticated but not trainees, so
    they get a 403 rather than being bounced to login."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if get_role(request.user) != Role.TRAINEE:
            raise PermissionDenied("This area is for trainees.")
        return view_func(request, *args, **kwargs)

    return wrapper

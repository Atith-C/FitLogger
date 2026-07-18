"""Template context shared across every page."""

# Which bottom tab is highlighted for a given URL namespace.
TAB_BY_APP = {
    "workouts": "home",
    "ai_planner": "plan",
    "analytics": "progress",
    "users": "profile",
}


def navigation(request):
    """Expose fl_tab (bottom-tab highlight) and is_admin (so trainee chrome —
    nav, tab bar, Joey — is hidden from admins). Derived server-side."""
    context = {
        "fl_tab": None,
        "is_admin": False,
        "unread_notifications": 0,
        "unread_messages": 0,
    }

    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        # Local imports avoid an app-loading cycle at import time.
        from notifications.services import unread_badges
        from users.services import get_or_create_profile

        is_admin = get_or_create_profile(user).is_admin
        context["is_admin"] = is_admin

        # Same helper the live poll uses, so the rendered badge and the polled
        # one cannot drift apart.
        badges = unread_badges(user, is_admin)
        context["unread_notifications"] = badges["notifications"]
        context["unread_messages"] = badges["messages"]

    match = request.resolver_match
    if match is not None:
        if match.url_name == "history":
            context["fl_tab"] = "history"
        else:
            context["fl_tab"] = TAB_BY_APP.get(match.app_name)

    return context

from django.apps import AppConfig
from django.contrib.auth.signals import user_logged_out


def _clear_joey_on_logout(sender, request, user, **kwargs):
    """Wipe the user's Joey conversation when they log out, so it lasts exactly
    one session and never carries over to the next person on a shared device."""
    if user is None:
        return
    from .services import clear_history

    clear_history(user)


class AssistantConfig(AppConfig):
    name = "assistant"

    def ready(self):
        user_logged_out.connect(
            _clear_joey_on_logout, dispatch_uid="assistant.clear_joey_on_logout"
        )

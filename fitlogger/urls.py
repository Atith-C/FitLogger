"""Root URL configuration for Fit Logger.

Each domain app owns its own urls.py and is mounted here under a namespace.
Apps are added to this file as their phases are implemented.
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("users.urls")),
    path("analytics/", include("analytics.urls")),
    path("plan/", include("ai_planner.urls")),
    path("assistant/", include("assistant.urls")),
    path("portal/", include("adminportal.urls")),
    path("notifications/", include("notifications.urls")),
    path("messages/", include("messaging.urls")),
    path("", include("workouts.urls")),
]

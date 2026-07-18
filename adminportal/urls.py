from django.urls import path

from messaging import views as messaging_views

from . import views

app_name = "adminportal"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("trainees/", views.trainees, name="trainees"),
    path("trainees/<int:trainee_id>/", views.trainee_detail, name="trainee_detail"),
    path("trainees/<int:trainee_id>/chat/", views.open_chat, name="open_chat"),
    path("trainees/<int:trainee_id>/blocked/", views.set_blocked, name="set_blocked"),
    path("trainees/<int:trainee_id>/delete/", views.delete_trainee, name="delete_trainee"),
    path("trainees/<int:trainee_id>/restore/", views.restore, name="restore"),
    path("analytics/", views.analytics, name="analytics"),
    path("settings/", views.settings_view, name="settings"),
    path("settings/save/", views.update_settings, name="update_settings"),
    path("exercises/", views.exercises, name="exercises"),
    path("exercises/add/", views.add_exercise, name="add_exercise"),
    path("exercises/<int:exercise_id>/delete/", views.delete_exercise, name="delete_exercise"),
    path("exercises/<int:exercise_id>/restore/", views.restore_exercise_view, name="restore_exercise"),
    # Admin-side messaging (views live in the messaging app).
    path("messages/", messaging_views.admin_messages, name="messages"),
    path("messages/<int:conversation_id>/", messaging_views.admin_conversation, name="conversation"),
]

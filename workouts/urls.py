from django.urls import path

from . import views

app_name = "workouts"

urlpatterns = [
    # "/" is the public landing page; the dashboard lives at /home/ so that a
    # signed-out visitor has something to land on. Nothing hardcodes these
    # paths — templates and tests both go through reverse().
    path("", views.landing, name="landing"),
    path("home/", views.home, name="home"),
    path("workout/start/", views.start_workout, name="start_workout"),
    path("workout/<int:session_id>/", views.active_workout, name="active_workout"),
    path("workout/<int:session_id>/log-set/", views.log_set, name="log_set"),
    path("workout/<int:session_id>/note/", views.save_note, name="save_note"),
    path("workout/<int:session_id>/finish/", views.finish_workout, name="finish_workout"),
    path("workout/<int:session_id>/delete/", views.delete_workout, name="delete_workout"),
    path("history/", views.history, name="history"),
    path("healthz/", views.healthz, name="healthz"),
]

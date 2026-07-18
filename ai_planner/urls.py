from django.urls import path

from . import views

app_name = "ai_planner"

urlpatterns = [
    path("", views.current_plan, name="current_plan"),
    path("generate/", views.generate_plan, name="generate_plan"),
    path("<int:plan_id>/", views.plan_detail, name="plan_detail"),
    path("<int:plan_id>/edit/", views.edit_plan, name="edit_plan"),
    path("<int:plan_id>/delete/", views.delete_plan, name="delete_plan"),
]

from django.urls import path

from . import views

app_name = "analytics"

urlpatterns = [
    path("progress/", views.progress, name="progress"),
    path("wellness/", views.wellness, name="wellness"),
    path("calories/", views.calories, name="calories"),
    path("calories/guide/", views.calorie_guide, name="calorie_guide"),
    path("nutrition/", views.nutrition, name="nutrition"),
]

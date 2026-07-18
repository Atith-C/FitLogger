from django.urls import path

from . import views

app_name = "messaging"

urlpatterns = [
    path("", views.inbox, name="inbox"),
    path("<int:conversation_id>/send/", views.send, name="send"),
    path("<int:conversation_id>/poll/", views.poll, name="poll"),
]

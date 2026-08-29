from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "users"

urlpatterns = [
    path("register/", views.register, name="register"),
    # Email verification. The token is signed, so it carries its own expiry
    # and there is no server-side record to store or clean up.
    path("verify/sent/", views.verify_sent, name="verify_sent"),
    path("verify/resend/", views.resend_verification, name="resend_verification"),
    path("verify/<str:token>/", views.verify_email, name="verify_email"),
    # Custom login carries the Trainee/Admin option and role-based redirect.
    path("login/", views.login_view, name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    # Forgotten username, password, or both. The token generator, its single
    # use and its expiry are Django's; only the address lookup and the wording
    # are ours.
    path("forgot/", views.ForgotAccountView.as_view(), name="password_reset"),
    path(
        "forgot/sent/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="users/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "forgot/set/<uidb64>/<token>/",
        views.SetNewPasswordView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "forgot/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="users/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    path("profile/", views.profile, name="profile"),
    path("profile/sharing/", views.toggle_profile_sharing, name="toggle_profile_sharing"),
]

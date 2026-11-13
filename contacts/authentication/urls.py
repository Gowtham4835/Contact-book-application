from django.urls import path
from .views import (
    RegistrationView,
    LoginView,
    LogoutView,
    PasswordResetRequestView,
    PasswordResetConfirmPageView,
    PasswordResetDonePageView,
    PasswordResetCompletePageView,
)

app_name = "authentication"
urlpatterns = [
    path("register/", RegistrationView.as_view(), name="register"),
    path("login/", LoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("password-reset/", PasswordResetRequestView.as_view(), name="password_reset"),
    path(
        "password-reset/done/",
        PasswordResetDonePageView.as_view(),
        name="password_reset_done",
    ),
    path(
        "password-reset/confirm/<uidb64>/<token>/",
        PasswordResetConfirmPageView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "password-reset/complete/",
        PasswordResetCompletePageView.as_view(),
        name="password_reset_complete",
    ),
]
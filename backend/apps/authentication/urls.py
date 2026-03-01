from django.urls import path

from .views import (
    ChangePasswordView,
    LoginView,
    LogoutView,
    RegisterView,
    TokenRefreshCustomView,
    UserProfileView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("token/refresh/", TokenRefreshCustomView.as_view(), name="auth-token-refresh"),
    path("profile/", UserProfileView.as_view(), name="auth-profile"),
    path("change-password/", ChangePasswordView.as_view(), name="auth-change-password"),
]

from django.urls import path

from .views import (
    ChangePasswordView,
    CheckVerificationView,
    LoginView,
    LogoutView,
    MFAConfirmSetupView,
    MFADisableView,
    MFASetupView,
    MFAVerifyView,
    OfflineVerifierStatusView,
    OfflineVerifierView,
    OrgDebugView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    PingView,
    RegisterView,
    AcceptTermsView,
    ResendVerificationView,
    SubAccountLoginView,
    TokenRefreshCustomView,
    UploadAvatarView,
    UserProfileView,
    VerifyEmailView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("staff-login/", SubAccountLoginView.as_view(), name="auth-staff-login"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("token/refresh/", TokenRefreshCustomView.as_view(), name="auth-token-refresh"),
    path("profile/", UserProfileView.as_view(), name="auth-profile"),
    path("accept-terms/", AcceptTermsView.as_view(), name="auth-accept-terms"),
    path("upload_avatar/", UploadAvatarView.as_view(), name="auth-upload-avatar"),
    path("change-password/", ChangePasswordView.as_view(), name="auth-change-password"),
    path("password-reset/", PasswordResetRequestView.as_view(), name="auth-password-reset"),
    path("password-reset/confirm/", PasswordResetConfirmView.as_view(), name="auth-password-reset-confirm"),
    # Email verification
    path("verify-email/", VerifyEmailView.as_view(), name="auth-verify-email"),
    path("resend-verification/", ResendVerificationView.as_view(), name="auth-resend-verification"),
    path("check-verification/", CheckVerificationView.as_view(), name="auth-check-verification"),
    # Connectivity probe (used by Tauri offline-detection)
    path("ping/", PingView.as_view(), name="auth-ping"),
    # Org-header diagnostic (JWT auth, no org required)
    path("org-debug/", OrgDebugView.as_view(), name="auth-org-debug"),
    # Offline re-authentication (desktop) — issue/rotate, status check, revoke
    path("offline-verifier/", OfflineVerifierView.as_view(), name="auth-offline-verifier"),
    path("offline-verifier/status/", OfflineVerifierStatusView.as_view(), name="auth-offline-verifier-status"),
    # MFA
    path("mfa/setup/", MFASetupView.as_view(), name="auth-mfa-setup"),
    path("mfa/confirm-setup/", MFAConfirmSetupView.as_view(), name="auth-mfa-confirm-setup"),
    path("mfa/verify/", MFAVerifyView.as_view(), name="auth-mfa-verify"),
    path("mfa/disable/", MFADisableView.as_view(), name="auth-mfa-disable"),
]

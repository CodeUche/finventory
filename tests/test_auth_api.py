"""
Authentication API tests.

Covers: register, login, logout, profile, token refresh.
"""

import pytest


@pytest.mark.integration
class TestRegistration:

    def test_register_returns_verification_message(self, api_client, db):
        """Successful registration should return 201 with a verification message (email verification required)."""
        response = api_client.post("/api/v1/auth/register/", {
            "email": "newuser@test.com",
            "first_name": "New",
            "last_name": "User",
            "password": "SecurePass2024!",
            "password_confirm": "SecurePass2024!",
            "terms_accepted": True,
        }, format="json")
        assert response.status_code == 201
        assert "message" in response.data

    def test_register_password_mismatch(self, api_client, db):
        """Mismatched passwords should return 400."""
        response = api_client.post("/api/v1/auth/register/", {
            "email": "user@test.com",
            "first_name": "A",
            "last_name": "B",
            "password": "Pass123456!",
            "password_confirm": "WrongPass!",
            "terms_accepted": True,
        }, format="json")
        assert response.status_code == 400
        # Envelope shape varies; what matters is that it failed on the
        # password check rather than being short-circuited by the
        # clickwrap gate, which is what used to happen here.
        assert "password_confirm" in str(response.data)

    def test_register_requires_accepting_the_terms(self, api_client, db):
        """Registration without clickwrap acceptance is refused.

        Acceptance of the Terms, Privacy Policy and DPA is a legal control
        recorded server-side, so it must be rejected here and not only hidden
        behind a disabled button in the UI.
        """
        response = api_client.post("/api/v1/auth/register/", {
            "email": "noterms@test.com",
            "first_name": "No",
            "last_name": "Terms",
            "password": "SecurePass2024!",
            "password_confirm": "SecurePass2024!",
        }, format="json")
        assert response.status_code == 400
        assert response.data["error"]["code"] == "terms_required"

    def test_register_established_duplicate_email(self, api_client, user, db):
        """Registering with an email that has an active org membership should return 400."""
        from apps.tenancy.models import Organisation, Membership
        org = Organisation.objects.create(name="Existing Org", slug="existing-org", currency="NGN", owner=user)
        Membership.objects.create(user=user, organisation=org, role="owner", is_active=True)
        response = api_client.post("/api/v1/auth/register/", {
            "email": user.email,
            "first_name": "Dup",
            "last_name": "User",
            "password": "Password2024!",
            "password_confirm": "Password2024!",
            "terms_accepted": True,
        }, format="json")
        assert response.status_code == 400
        assert response.data["error"]["code"] == "email_taken"


@pytest.mark.integration
class TestLogin:

    def test_login_returns_tokens(self, api_client, user):
        """Valid credentials should return access and refresh tokens."""
        response = api_client.post("/api/v1/auth/login/", {
            "email": user.email,
            "password": "StrongPass123!",
        }, format="json")
        assert response.status_code == 200
        assert "access" in response.data
        assert "refresh" in response.data

    def test_login_invalid_credentials(self, api_client, user):
        """Wrong password should return 401."""
        response = api_client.post("/api/v1/auth/login/", {
            "email": user.email,
            "password": "wrongpassword",
        }, format="json")
        assert response.status_code == 401

    def test_profile_requires_auth(self, api_client):
        """Profile endpoint should require authentication."""
        response = api_client.get("/api/v1/auth/profile/")
        assert response.status_code == 401

    def test_profile_returns_user_data(self, auth_client, user):
        """Authenticated user should get their profile."""
        response = auth_client.get("/api/v1/auth/profile/")
        assert response.status_code == 200
        assert response.data["email"] == user.email

"""
Authentication API tests.

Covers: register, login, logout, profile, token refresh.
"""

import pytest


@pytest.mark.integration
class TestRegistration:

    def test_register_returns_tokens(self, api_client, db):
        """Successful registration should return JWT tokens."""
        response = api_client.post("/api/v1/auth/register/", {
            "email": "newuser@test.com",
            "first_name": "New",
            "last_name": "User",
            "password": "SecurePass2024!",
            "password_confirm": "SecurePass2024!",
        }, format="json")
        assert response.status_code == 201
        assert "tokens" in response.data
        assert "access" in response.data["tokens"]
        assert "refresh" in response.data["tokens"]

    def test_register_password_mismatch(self, api_client, db):
        """Mismatched passwords should return 400."""
        response = api_client.post("/api/v1/auth/register/", {
            "email": "user@test.com",
            "first_name": "A",
            "last_name": "B",
            "password": "Pass123456!",
            "password_confirm": "WrongPass!",
        }, format="json")
        assert response.status_code == 400

    def test_register_duplicate_email(self, api_client, user, db):
        """Registering with an existing email should return 400."""
        response = api_client.post("/api/v1/auth/register/", {
            "email": user.email,
            "first_name": "Dup",
            "last_name": "User",
            "password": "Password2024!",
            "password_confirm": "Password2024!",
        }, format="json")
        assert response.status_code == 400


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

"""Tests for the enabled_payment_types setting (POS / invoice-collection tender toggles).

New test file rather than an addition to tests.py: kept isolated so this
change never touches unrelated in-flight work in tests.py.
"""

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.tenancy.models import Organisation, PAYMENT_TYPE_CHOICES
from apps.tenancy.services import OrganisationService


def _make_user(email="payer@example.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="Test", last_name="User", is_verified=True,
    )


def _make_org(user, name="Payment Types Org"):
    return OrganisationService.create_organisation(
        name=name, owner=user, extra={"currency": "NGN", "country": "NG"},
    )


def _auth_client(user, org):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}",
        HTTP_X_ORGANISATION_ID=str(org.id),
    )
    return client


class EnabledPaymentTypesDefaultTests(TestCase):
    """A fresh org, or an existing org that never touched this setting, must
    see exactly the tender types it always had — no behaviour change."""

    def setUp(self):
        self.owner = _make_user()
        self.org = _make_org(self.owner)

    def test_new_org_has_every_tender_type_enabled(self):
        self.org.refresh_from_db()
        self.assertEqual(sorted(self.org.enabled_payment_types), sorted(PAYMENT_TYPE_CHOICES))

    def test_default_is_returned_over_the_api(self):
        client = _auth_client(self.owner, self.org)
        res = client.get(f"/api/v1/tenancy/organisations/{self.org.id}/")
        # Org detail is served via list/retrieve — fall back to list if retrieve isn't routed.
        if res.status_code == 404:
            res = client.get("/api/v1/tenancy/organisations/")
            data = res.data["results"][0] if isinstance(res.data, dict) and "results" in res.data else res.data[0]
        else:
            data = res.data
        self.assertEqual(sorted(data["enabled_payment_types"]), sorted(PAYMENT_TYPE_CHOICES))


class EnabledPaymentTypesUpdateTests(TestCase):
    """The setting persists through the normal organisation PATCH endpoint,
    the same one every other org-settings toggle already uses."""

    def setUp(self):
        self.owner = _make_user("update.owner@example.com")
        self.org = _make_org(self.owner, "Update Org")
        self.client = _auth_client(self.owner, self.org)

    def test_i_can_disable_one_tender_type(self):
        res = self.client.patch(
            f"/api/v1/tenancy/organisations/{self.org.id}/",
            {"enabled_payment_types": ["cash", "bank_transfer"]},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.org.refresh_from_db()
        self.assertEqual(sorted(self.org.enabled_payment_types), ["bank_transfer", "cash"])
        self.assertNotIn("card", self.org.enabled_payment_types)
        self.assertNotIn("wallet", self.org.enabled_payment_types)

    def test_setting_is_scoped_to_its_own_organisation(self):
        """Org A disabling a tender type must never affect org B."""
        other_owner = _make_user("other.owner@example.com")
        other_org = _make_org(other_owner, "Other Org")

        self.client.patch(
            f"/api/v1/tenancy/organisations/{self.org.id}/",
            {"enabled_payment_types": ["cash"]},
            format="json",
        )
        other_org.refresh_from_db()
        self.assertEqual(sorted(other_org.enabled_payment_types), sorted(PAYMENT_TYPE_CHOICES))

    def test_an_unrecognised_value_is_still_stored_permissively(self):
        """The field is deliberately free-form, matching TillTenderCount.method,
        so a merchant who already uses a custom tender label is never blocked."""
        res = self.client.patch(
            f"/api/v1/tenancy/organisations/{self.org.id}/",
            {"enabled_payment_types": ["cash", "pos_terminal_x"]},
            format="json",
        )
        self.assertEqual(res.status_code, 200, res.content)
        self.org.refresh_from_db()
        self.assertIn("pos_terminal_x", self.org.enabled_payment_types)

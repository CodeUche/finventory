"""Tests for tenancy: organisation creation, invitations, sub-accounts, memberships."""

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.tenancy.models import Membership, Organisation
from apps.tenancy.services import OrganisationService


def _make_user(email="owner@example.com", password="TestPass123!"):
    return User.objects.create_user(
        email=email, password=password,
        first_name="Test", last_name="User", is_verified=True,
    )


def _make_org(user, name="Test Org"):
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


class OrganisationCreateTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _make_user()
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")

    def test_create_org_via_api(self):
        res = self.client.post("/api/v1/tenancy/organisations/", {
            "name": "My Business",
            "currency": "NGN",
            "country": "NG",
        })
        self.assertEqual(res.status_code, 201)
        self.assertTrue(Organisation.objects.filter(name="My Business").exists())

    def test_create_org_owner_membership_created(self):
        res = self.client.post("/api/v1/tenancy/organisations/", {
            "name": "Auto-Membership Org",
            "currency": "NGN",
            "country": "NG",
        })
        self.assertEqual(res.status_code, 201)
        org_id = res.data["id"]
        org = Organisation.objects.get(id=org_id)
        self.assertTrue(
            Membership.objects.filter(user=self.user, organisation=org, role="owner").exists()
        )

    def test_create_org_seeds_coa(self):
        from apps.accounting.models import Account
        self.client.post("/api/v1/tenancy/organisations/", {
            "name": "COA Seed Org",
            "currency": "NGN",
            "country": "NG",
        })
        org = Organisation.objects.get(name="COA Seed Org")
        self.assertGreater(Account.objects.filter(organisation=org).count(), 0)


class OrganisationRetrieveTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.org = _make_org(self.user)
        self.client = _auth_client(self.user, self.org)

    def test_list_my_organisations(self):
        res = self.client.get("/api/v1/tenancy/organisations/")
        self.assertEqual(res.status_code, 200)
        ids = [o["id"] for o in (res.data.get("results") or res.data)]
        self.assertIn(str(self.org.id), ids)

    def test_retrieve_org_detail(self):
        res = self.client.get(f"/api/v1/tenancy/organisations/{self.org.id}/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["name"], self.org.name)

    def test_other_user_cannot_see_org(self):
        other = _make_user("other@example.com")
        other_org = _make_org(other, "Other Org")
        c = _auth_client(other, other_org)
        res = c.get(f"/api/v1/tenancy/organisations/{self.org.id}/")
        self.assertIn(res.status_code, [403, 404])


class SubAccountTests(TestCase):
    def setUp(self):
        self.owner = _make_user("owner2@example.com")
        self.org = _make_org(self.owner)
        self.client = _auth_client(self.owner, self.org)

    def test_create_subaccount_sets_must_change_password(self):
        res = self.client.post(
            f"/api/v1/tenancy/organisations/{self.org.id}/create_subaccount/",
            {
                "username": "staffjohn",
                "first_name": "John",
                "last_name": "Staff",
                "role": "staff",
                "password": "TempPass123!",
            },
        )
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        # Email is constructed as username@org_slug
        expected_email = f"staffjohn@{self.org.slug}"
        user = User.objects.get(email=expected_email)
        self.assertTrue(user.must_change_password)

    def test_create_subaccount_creates_membership(self):
        res = self.client.post(
            f"/api/v1/tenancy/organisations/{self.org.id}/create_subaccount/",
            {
                "username": "staffjane",
                "first_name": "Jane",
                "last_name": "Staff",
                "role": "staff",
                "password": "TempPass456!",
            },
        )
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        expected_email = f"staffjane@{self.org.slug}"
        sub_user = User.objects.get(email=expected_email)
        self.assertTrue(
            Membership.objects.filter(user=sub_user, organisation=self.org).exists()
        )


class MembershipPermissionTests(TestCase):
    def setUp(self):
        self.owner = _make_user("perm_owner@example.com")
        self.org = _make_org(self.owner)
        self.member = _make_user("perm_member@example.com")
        Membership.objects.create(
            user=self.member, organisation=self.org, role="staff", is_active=True
        )
        self.client = _auth_client(self.owner, self.org)

    def test_owner_can_list_memberships(self):
        res = self.client.get("/api/v1/tenancy/memberships/")
        self.assertEqual(res.status_code, 200)

    def test_staff_cannot_invite(self):
        staff_client = _auth_client(self.member, self.org)
        res = staff_client.post(
            f"/api/v1/tenancy/organisations/{self.org.id}/invite/",
            {"email": "new@example.com", "role": "staff"},
        )
        self.assertIn(res.status_code, [403, 400])


class OrganisationMutationPermissionTests(TestCase):
    """C-1 — the org object itself is a privileged resource.

    Before the fix, OrganisationViewSet declared only `permission_classes =
    [IsAuthenticated]` and never overrode the ModelViewSet defaults, so *any*
    active member — down to `viewer`/`employee` — could rewrite the payout bank
    account or soft-delete the whole organisation in one request.

    These tests pin the boundary in both directions: privileged fields are
    refused below the minimum role, and the benign fields the product actually
    depends on (TopBar currency switch, onboarding completion) still work for
    ordinary members.
    """

    # Roles that must NOT be able to rewrite payout bank details.
    # `admin` is deliberately excluded: SettingsPage renders an editable bank form
    # for admins, so gating bank details at owner-only would 403 a form the UI
    # presents as editable. admin+ still closes the reported hole.
    ROLES_DENIED_BANK = ["viewer", "employee", "staff", "accountant", "manager"]
    # Deactivate/delete are owner-only — no frontend path exercises either, so the
    # tighter gate has no UI cost. `admin` IS included here.
    ROLES_DENIED_DESTRUCTIVE = ROLES_DENIED_BANK + ["admin"]

    def setUp(self):
        self.owner = _make_user("c1_owner@example.com")
        self.org = _make_org(self.owner, name="C1 Org")
        self.org.bank_account_number = "0000000000"
        self.org.bank_name = "Original Bank"
        self.org.save(update_fields=["bank_account_number", "bank_name"])
        self.url = f"/api/v1/tenancy/organisations/{self.org.id}/"

    def _client_with_role(self, role):
        user = _make_user(f"c1_{role}@example.com")
        Membership.objects.create(
            user=user, organisation=self.org, role=role, is_active=True
        )
        return _auth_client(user, self.org)

    # ---- bank details -------------------------------------------------

    def test_bank_details_patch_refused_for_every_role_below_admin(self):
        for role in self.ROLES_DENIED_BANK:
            with self.subTest(role=role):
                client = self._client_with_role(role)
                res = client.patch(
                    self.url,
                    {"bank_account_number": "9999999999", "bank_name": "Attacker Bank"},
                    format="json",
                )
                self.assertEqual(
                    res.status_code, 403,
                    f"role={role} must not change payout bank details (got {res.status_code})",
                )
                self.org.refresh_from_db()
                self.assertEqual(self.org.bank_account_number, "0000000000")
                self.assertEqual(self.org.bank_name, "Original Bank")

    def test_bank_details_patch_allowed_for_owner(self):
        client = _auth_client(self.owner, self.org)
        res = client.patch(
            self.url,
            {"bank_account_number": "1234567890", "bank_name": "New Bank"},
            format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.org.refresh_from_db()
        self.assertEqual(self.org.bank_account_number, "1234567890")

    def test_bank_details_patch_allowed_for_admin(self):
        """SettingsPage shows admins an editable bank form — it must keep working."""
        client = self._client_with_role("admin")
        res = client.patch(self.url, {"bank_account_number": "2222222222"}, format="json")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.org.refresh_from_db()
        self.assertEqual(self.org.bank_account_number, "2222222222")

    def test_bank_detail_change_is_individually_audited(self):
        from apps.core.models import AuditLog

        client = _auth_client(self.owner, self.org)
        client.patch(self.url, {"bank_account_number": "5555555555"}, format="json")

        entry = AuditLog.objects.filter(
            organisation_id=self.org.id, model_name="tenancy/organisations"
        ).order_by("-created_at").first()
        self.assertIsNotNone(entry, "bank detail change must write an audit entry")
        self.assertIn("bank_account_number", entry.changes)
        self.assertEqual(entry.changes["bank_account_number"]["from"], "0000000000")
        self.assertEqual(entry.changes["bank_account_number"]["to"], "5555555555")

    # ---- is_active / destroy ------------------------------------------

    def test_is_active_patch_refused_for_every_role_below_owner(self):
        for role in self.ROLES_DENIED_DESTRUCTIVE:
            with self.subTest(role=role):
                client = self._client_with_role(role)
                res = client.patch(self.url, {"is_active": False}, format="json")
                self.assertEqual(
                    res.status_code, 403,
                    f"role={role} must not be able to deactivate the org (got {res.status_code})",
                )
                self.org.refresh_from_db()
                self.assertTrue(self.org.is_active)

    def test_destroy_refused_for_every_role_below_owner(self):
        for role in self.ROLES_DENIED_DESTRUCTIVE:
            with self.subTest(role=role):
                client = self._client_with_role(role)
                res = client.delete(self.url)
                self.assertEqual(
                    res.status_code, 403,
                    f"role={role} must not be able to delete the org (got {res.status_code})",
                )
                self.assertTrue(
                    Organisation.objects.filter(id=self.org.id, is_deleted=False).exists()
                )

    # ---- regression guards: benign fields must keep working ------------

    def test_staff_can_still_patch_currency(self):
        """TopBar.handleCurrencyChange has no role gate — it must not start 403-ing."""
        client = self._client_with_role("staff")
        res = client.patch(self.url, {"currency": "USD"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.org.refresh_from_db()
        self.assertEqual(self.org.currency, "USD")

    def test_staff_can_still_patch_benign_profile_fields(self):
        client = self._client_with_role("staff")
        res = client.patch(
            self.url, {"phone": "+2348012345678", "address": "12 New Road"}, format="json"
        )
        self.assertEqual(res.status_code, 200)

    def test_owner_can_still_complete_onboarding(self):
        """OnboardingPage PATCHes onboarding_completed — must remain available."""
        client = _auth_client(self.owner, self.org)
        res = client.patch(self.url, {"onboarding_completed": True}, format="json")
        self.assertEqual(res.status_code, 200)

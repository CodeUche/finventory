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

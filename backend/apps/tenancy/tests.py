"""Tests for tenancy: organisation creation, invitations, sub-accounts, memberships."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.tenancy.models import Invitation, Membership, Organisation
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


class InviteOwnerEscalationTests(TestCase):
    """
    Finding H-1.

    The invite action is open to admins (IsOwnerOrAdmin), and its only role
    check is `role in Membership.Role.choices` — which OWNER satisfies.
    accept_invitation() then writes invitation.role onto the membership with no
    guard of its own, so an admin could mint a second owner by inviting an
    address they control.

    The same "only one owner" rule is already enforced on the two sibling
    paths — create_subaccount and MembershipViewSet.partial_update — so this is
    a gap in one of three, not a missing policy. That is the third time this
    shape has appeared (C-1, NEW-12, and now here): a control present on one
    route and absent on its sibling.

    Owner is the role that can rewrite bank details and delete the
    organisation, so a second one is a full takeover of the tenant.
    """

    def setUp(self):
        from apps.accounting.tests import _upgrade_to_business

        self.owner = _make_user("h1_owner@example.com")
        self.org = _make_org(self.owner, "H1 Org")
        # The free plan caps members at 1, so every invite returns 400 for a
        # plan reason. Without this the owner-escalation test passes without
        # ever reaching the role check — green, and proving nothing.
        _upgrade_to_business(self.org)
        self.admin = _make_user("h1_admin@example.com")
        Membership.objects.create(
            user=self.admin, organisation=self.org, role="admin", is_active=True,
        )
        self.admin_client = _auth_client(self.admin, self.org)

    def test_admin_cannot_invite_someone_as_owner(self):
        res = self.admin_client.post(
            f"/api/v1/tenancy/organisations/{self.org.id}/invite/",
            {"email": "attacker@evil.com", "role": "owner"},
            format="json",
        )
        self.assertIn(
            res.status_code, (400, 403, 422),
            "an admin invited a new OWNER — that role can rewrite bank details "
            "and delete the organisation (H-1)",
        )
        self.assertFalse(
            Invitation.objects.filter(organisation=self.org, role="owner").exists(),
            "an owner-role invitation was created",
        )

    def test_accepting_an_owner_invitation_cannot_create_a_second_owner(self):
        """
        Defence at the mutation point, not just the endpoint.

        Even if an owner-role Invitation exists — from a pre-fix row, or a
        future caller that skips the view — accepting it must not produce a
        second owner.
        """
        invitation = Invitation.objects.create(
            organisation=self.org, email="attacker2@evil.com", role="owner",
            invited_by=self.admin, expires_at=timezone.now() + timedelta(days=7),
        )
        joiner = _make_user("h1_joiner@example.com")
        try:
            OrganisationService.accept_invitation(invitation, joiner)
        except Exception:
            pass  # rejecting outright is an acceptable outcome

        owners = Membership.objects.filter(
            organisation=self.org, role="owner", is_active=True,
        )
        self.assertEqual(
            owners.count(), 1,
            "accepting an owner invitation produced a second owner — the "
            "one-owner invariant other code relies on is broken",
        )
        self.assertEqual(owners.first().user_id, self.owner.id)

    def test_admin_can_still_invite_normal_roles(self):
        """The gate must not break ordinary team invitations."""
        for role in ("staff", "manager", "accountant", "viewer"):
            with self.subTest(role=role):
                res = self.admin_client.post(
                    f"/api/v1/tenancy/organisations/{self.org.id}/invite/",
                    {"email": f"colleague_{role}@example.com", "role": role},
                    format="json",
                )
                self.assertEqual(
                    res.status_code, 201,
                    f"inviting a {role} broke — the fix is too broad",
                )


class DemoAccountCommandTests(TestCase):
    """The demo account exists so click-throughs have somewhere to sign in on a
    real deployment. Its safety rests entirely on never resting in an enabled
    state with a known password, so the locks are pinned here."""

    EMAIL = "cmd.demo@audity.test"

    def setUp(self):
        from apps.authentication.models import User
        self.user = User.objects.create_user(
            email=self.EMAIL, password="initial-Passw0rd!", first_name="Cmd", last_name="Demo",
        )

    def _run(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("demo_account", *args, stdout=out)
        return out.getvalue()

    def _refresh(self):
        self.user.refresh_from_db()
        return self.user

    # ── activate / deactivate ────────────────────────────────────────────────
    def test_deactivate_restores_every_lock(self):
        self._run("--deactivate", "--email", self.EMAIL)
        u = self._refresh()
        self.assertFalse(u.is_active)
        self.assertFalse(u.is_verified)
        self.assertFalse(u.has_usable_password(),
                         "the old password must stop being a password at all")

    def test_activate_enables_and_prints_a_password_once(self):
        out = self._run("--activate", "--email", self.EMAIL)
        u = self._refresh()
        self.assertTrue(u.is_active)
        self.assertTrue(u.is_verified)
        self.assertTrue(u.has_usable_password())
        self.assertIn("shown ONCE", out)

    def test_each_activation_mints_a_different_password(self):
        """A reused password is the whole failure mode this command prevents."""
        first = self._run("--activate", "--email", self.EMAIL)
        hash_one = self._refresh().password
        self._run("--deactivate", "--email", self.EMAIL)
        second = self._run("--activate", "--email", self.EMAIL)
        hash_two = self._refresh().password
        self.assertNotEqual(hash_one, hash_two)
        self.assertNotEqual(first, second)

    def test_password_printed_actually_works_then_stops_working(self):
        """End to end: the printed password authenticates, and after
        --deactivate nothing does."""
        import re
        from django.contrib.auth import authenticate
        out = self._run("--activate", "--email", self.EMAIL)
        m = re.search(r"E2E_RECON_PASSWORD='([^']+)'", out)
        self.assertIsNotNone(m, out)
        pw = m.group(1)
        self.assertIsNotNone(authenticate(username=self.EMAIL, password=pw))

        self._run("--deactivate", "--email", self.EMAIL)
        self.assertIsNone(authenticate(username=self.EMAIL, password=pw),
                          "the printed password must be dead after deactivation")

    def test_status_reports_without_changing_anything(self):
        self._run("--deactivate", "--email", self.EMAIL)
        before = self._refresh().password
        out = self._run("--status", "--email", self.EMAIL)
        self.assertIn("LOCKED", out)
        self.assertEqual(self._refresh().password, before)

    # ── refusals — these are the guardrails, not niceties ────────────────────
    def test_refuses_a_real_domain(self):
        from django.core.management.base import CommandError
        from apps.authentication.models import User
        User.objects.create_user(email="real.person@gmail.com", password="x-Passw0rd!1")
        with self.assertRaises(CommandError):
            self._run("--deactivate", "--email", "real.person@gmail.com")

    def test_refuses_a_staff_or_superuser_account(self):
        from django.core.management.base import CommandError
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        with self.assertRaises(CommandError):
            self._run("--activate", "--email", self.EMAIL)

    def test_refuses_an_unknown_account(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            self._run("--status", "--email", "nobody@audity.test")


class OrganisationSlugCollisionTests(TestCase):
    """A colliding organisation name must still create, including when the slug is
    held by a SOFT-DELETED organisation.

    The unique constraint on slug does not exclude soft-deleted rows, so a
    discarded organisation keeps its slug forever. The retry that is supposed to
    recover ran inside the caller's atomic block with no savepoint, so the
    IntegrityError poisoned the transaction and the next query raised
    TransactionManagementError. Signup failed outright with "Failed to create
    organisation" — reproduced against production before this was fixed.
    """

    def setUp(self):
        self.owner = User.objects.create_user(email="slug.owner@audity.test", password="Passw0rd!123")
        self.other = User.objects.create_user(email="slug.other@audity.test", password="Passw0rd!123")

    def test_same_name_twice_still_creates(self):
        a = OrganisationService.create_organisation("Recon Demo Ltd", self.owner)
        b = OrganisationService.create_organisation("Recon Demo Ltd", self.other)
        self.assertNotEqual(a.id, b.id)
        self.assertNotEqual(a.slug, b.slug, "the second organisation needs its own slug")

    def test_slug_held_by_a_soft_deleted_organisation_does_not_block_signup(self):
        first = OrganisationService.create_organisation("Recon Demo Ltd", self.owner)
        held = first.slug
        first.delete()  # soft delete — the row, and its slug, remain
        self.assertTrue(Organisation.all_objects.filter(slug=held, is_deleted=True).exists())

        again = OrganisationService.create_organisation("Recon Demo Ltd", self.other)
        self.assertIsNotNone(again.id)
        self.assertNotEqual(again.slug, held)

    def test_the_new_organisation_is_usable_afterwards(self):
        """A savepoint rollback must not leave the outer transaction broken —
        membership creation and chart-of-accounts seeding still have to run."""
        OrganisationService.create_organisation("Recon Demo Ltd", self.owner)
        org = OrganisationService.create_organisation("Recon Demo Ltd", self.other)
        self.assertTrue(
            Membership.objects.filter(organisation=org, user=self.other, role=Membership.Role.OWNER).exists(),
            "membership must still be created after a slug retry",
        )
        from apps.accounting.models import Account
        self.assertGreater(
            Account.objects.filter(organisation=org).count(), 0,
            "the chart of accounts must still seed after a slug retry",
        )

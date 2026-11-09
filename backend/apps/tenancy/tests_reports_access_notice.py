"""The owner's one-tap fix for Reports becoming a per-person tick."""

from django.test import TestCase

from apps.tenancy.models import Membership, ModulePermission
from apps.tenancy.tests_payment_types import _auth_client, _make_org, _make_user


class ReportsAccessNoticeTests(TestCase):
    def setUp(self):
        self.owner = _make_user("owner-notice@example.com")
        self.org = _make_org(self.owner, "Notice Org")
        self.client_owner = _auth_client(self.owner, self.org)
        self.has = self._member("has@example.com", "accountant")
        ModulePermission.objects.create(membership=self.has, module="reports", access_level="view")
        self.lacks = self._member("lacks@example.com", "staff")
        ModulePermission.objects.create(membership=self.lacks, module="sales", access_level="edit")

    def _member(self, email, role):
        return Membership.objects.create(user=_make_user(email), organisation=self.org, role=role, is_active=True)

    def test_lists_only_people_who_cannot_open_reports(self):
        res = self.client_owner.get("/api/v1/tenancy/memberships/reports_access_gap/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual([m["id"] for m in res.data["members"]], [str(self.lacks.id)])

    def test_grant_gives_view_only_reports_and_nothing_else(self):
        res = self.client_owner.post("/api/v1/tenancy/memberships/grant_reports/",
                                     {"membership_ids": [str(self.lacks.id)]}, format="json")
        self.assertEqual(res.data["granted"], 1)
        self.assertEqual(ModulePermission.objects.get(membership=self.lacks, module="reports").access_level, "view")
        self.assertEqual(ModulePermission.objects.get(membership=self.lacks, module="sales").access_level, "edit")
        self.assertEqual(self.client_owner.get("/api/v1/tenancy/memberships/reports_access_gap/").data["members"], [])

    def test_grant_only_touches_the_people_named(self):
        other = self._member("other@example.com", "viewer")
        self.client_owner.post("/api/v1/tenancy/memberships/grant_reports/",
                               {"membership_ids": [str(self.lacks.id)]}, format="json")
        self.assertFalse(ModulePermission.objects.filter(membership=other, module="reports").exists())

    def test_a_team_member_cannot_use_it(self):
        member_client = _auth_client(self.lacks.user, self.org)
        res = member_client.post("/api/v1/tenancy/memberships/grant_reports/",
                                 {"membership_ids": [str(self.lacks.id)]}, format="json")
        self.assertEqual(res.status_code, 403)
        self.assertFalse(ModulePermission.objects.filter(membership=self.lacks, module="reports").exists())

from django.test import TestCase

from apps.accounting.tests import _make_user, _make_org, _upgrade_to_business, _auth_client
from apps.helpdesk.models import SupportTicket


class HelpDeskTests(TestCase):
    def setUp(self):
        self.user = _make_user("hd_owner@example.com")
        self.org = _make_org(self.user, "HD Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)

    def test_create_and_list_ticket(self):
        res = self.client.post("/api/v1/helpdesk/tickets/", {
            "subject": "Cannot print receipt", "description": "POS receipt not printing",
            "priority": "high", "category": "POS",
        }, format="json")
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertTrue(res.data["ticket_number"].startswith("TKT-"))
        listing = self.client.get("/api/v1/helpdesk/tickets/")
        self.assertEqual(listing.status_code, 200)
        data = listing.data.get("results", listing.data)
        self.assertEqual(len(data), 1)

    def test_comment_and_resolve(self):
        res = self.client.post("/api/v1/helpdesk/tickets/", {"subject": "Question"}, format="json")
        tid = res.data["id"]
        c = self.client.post(f"/api/v1/helpdesk/tickets/{tid}/comment/", {"body": "Looking into it"}, format="json")
        self.assertEqual(c.status_code, 201, msg=str(c.data))
        s = self.client.post(f"/api/v1/helpdesk/tickets/{tid}/set_status/", {"status": "resolved"}, format="json")
        self.assertEqual(s.status_code, 200, msg=str(s.data))
        self.assertEqual(s.data["status"], "resolved")
        self.assertIsNotNone(s.data["resolved_at"])
        SupportTicket.objects.get(id=tid)  # exists

    def test_tenant_isolation(self):
        res = self.client.post("/api/v1/helpdesk/tickets/", {"subject": "Mine"}, format="json")
        tid = res.data["id"]
        other = _make_user("hd_other@example.com")
        other_org = _make_org(other, "Other HD Org")
        _upgrade_to_business(other_org)
        oc = _auth_client(other, other_org)
        got = oc.get(f"/api/v1/helpdesk/tickets/{tid}/")
        self.assertIn(got.status_code, [403, 404])

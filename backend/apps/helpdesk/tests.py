from django.core import mail
from django.test import TestCase

from apps.accounting.tests import _make_user, _make_org, _upgrade_to_business, _auth_client
from apps.helpdesk.models import SupportTicket


def _make_superuser(email):
    su = _make_user(email)
    su.is_superuser = True
    su.is_staff = True
    su.save(update_fields=["is_superuser", "is_staff"])
    return su


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

    def test_create_emails_support_inbox(self):
        mail.outbox = []
        res = self.client.post("/api/v1/helpdesk/tickets/", {
            "subject": "Printer down", "description": "Help", "priority": "urgent",
        }, format="json")
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertIn("support@auditytechnologies.com", msg.to)
        self.assertIn(res.data["ticket_number"], msg.subject)
        # Support can reply straight to the customer.
        self.assertEqual(msg.reply_to, [self.user.email])

    def test_customer_comment_emails_support_inbox(self):
        res = self.client.post("/api/v1/helpdesk/tickets/", {"subject": "Q"}, format="json")
        tid = res.data["id"]
        mail.outbox = []
        c = self.client.post(f"/api/v1/helpdesk/tickets/{tid}/comment/", {"body": "any update?"}, format="json")
        self.assertEqual(c.status_code, 201, msg=str(c.data))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("support@auditytechnologies.com", mail.outbox[0].to)


class PlatformInboxTests(TestCase):
    def setUp(self):
        self.owner = _make_user("hd_owner2@example.com")
        self.org = _make_org(self.owner, "Inbox Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.owner, self.org)
        # A second org's ticket, to prove cross-org visibility.
        self.owner_b = _make_user("hd_owner_b@example.com")
        self.org_b = _make_org(self.owner_b, "Inbox Org B")
        _upgrade_to_business(self.org_b)
        self.client_b = _auth_client(self.owner_b, self.org_b)
        self.client.post("/api/v1/helpdesk/tickets/", {"subject": "From A"}, format="json")
        self.client_b.post("/api/v1/helpdesk/tickets/", {"subject": "From B"}, format="json")

    def test_superuser_sees_all_orgs(self):
        su = _make_superuser("hd_super@example.com")
        sc = _auth_client(su, self.org)
        res = sc.get("/api/v1/platform/tickets/")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        rows = res.data.get("results", res.data)
        subjects = {r["subject"] for r in rows}
        self.assertEqual({"From A", "From B"}, subjects)
        self.assertTrue(all("organisation_name" in r for r in rows))

    def test_non_superuser_forbidden(self):
        res = self.client.get("/api/v1/platform/tickets/")
        self.assertIn(res.status_code, [403, 401])

    def test_support_reply_notifies_creator(self):
        su = _make_superuser("hd_super2@example.com")
        sc = _auth_client(su, self.org)
        tid = SupportTicket.objects.get(subject="From A").id
        mail.outbox = []
        r = sc.post(f"/api/v1/platform/tickets/{tid}/reply/", {"body": "We're on it."}, format="json")
        self.assertEqual(r.status_code, 201, msg=str(r.data))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.owner.email, mail.outbox[0].to)

    def test_assign_to_self(self):
        su = _make_superuser("hd_super3@example.com")
        sc = _auth_client(su, self.org)
        tid = SupportTicket.objects.get(subject="From B").id
        r = sc.post(f"/api/v1/platform/tickets/{tid}/assign/", {}, format="json")
        self.assertEqual(r.status_code, 200, msg=str(r.data))
        self.assertEqual(str(r.data["assigned_to"]), str(su.id))

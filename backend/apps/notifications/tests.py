"""
Notification bell — storage, access and preferences.

The access rule is the important one: your bell is yours. A notification is
addressed to a person, so there is no org-wide list — letting a manager read
the whole organisation's bell would leak, for example, that a colleague
requested leave.
"""

from django.test import TestCase

from apps.payroll.test_track_a import _make_user, _make_org, _auth_client
from apps.tenancy.models import Membership

from .models import Notification, NotificationPreference


def _member(org, email, role="staff"):
    user = _make_user(email)
    membership = Membership.objects.create(
        user=user, organisation=org, role=role, is_active=True,
    )
    return user, _auth_client(user, org), membership


def _titles(res):
    """Titles from a list response, paginated or not — [] when empty."""
    data = res.data
    if isinstance(data, dict):
        data = data.get("results", [])
    return [n["title"] for n in data]


def _notify(org, user, title="Something happened", category="leave", read=False):
    return Notification.objects.create(
        organisation=org, recipient=user, category=category,
        title=title, body="Detail", link="/hr/leave", is_read=read,
    )


class NotificationAccessTests(TestCase):
    def setUp(self):
        self.owner = _make_user("notif_owner@example.com")
        self.org = _make_org(self.owner, "Notif Org")
        self.owner_client = _auth_client(self.owner, self.org)
        self.other, self.other_client, _ = _member(self.org, "notif_other@example.com")

    def test_i_see_my_own_notifications(self):
        _notify(self.org, self.owner, "Mine")
        res = self.owner_client.get("/api/v1/notifications/")
        self.assertEqual(res.status_code, 200)
        titles = _titles(res)
        self.assertIn("Mine", titles)

    def test_i_cannot_see_someone_elses(self):
        _notify(self.org, self.other, "Colleague's private business")
        res = self.owner_client.get("/api/v1/notifications/")
        titles = _titles(res)
        self.assertNotIn(
            "Colleague's private business", titles,
            "one person's bell showed another person's notifications",
        )

    def test_i_cannot_open_someone_elses_by_id(self):
        theirs = _notify(self.org, self.other, "Not for me")
        res = self.owner_client.get(f"/api/v1/notifications/{theirs.id}/")
        self.assertEqual(
            res.status_code, 404,
            "a notification addressed to someone else was readable by id",
        )

    def test_unread_count_is_mine_only(self):
        _notify(self.org, self.owner, "A")
        _notify(self.org, self.owner, "B", read=True)
        _notify(self.org, self.other, "Theirs")
        res = self.owner_client.get("/api/v1/notifications/unread_count/")
        self.assertEqual(res.data["count"], 1)

    def test_mark_read(self):
        n = _notify(self.org, self.owner, "Unread")
        res = self.owner_client.post(f"/api/v1/notifications/{n.id}/mark_read/")
        self.assertEqual(res.status_code, 200)
        n.refresh_from_db()
        self.assertTrue(n.is_read)
        self.assertIsNotNone(n.read_at)

    def test_mark_all_read_does_not_touch_other_people(self):
        _notify(self.org, self.owner, "Mine 1")
        _notify(self.org, self.owner, "Mine 2")
        theirs = _notify(self.org, self.other, "Theirs")
        res = self.owner_client.post("/api/v1/notifications/mark_all_read/")
        self.assertEqual(res.data["marked"], 2)
        theirs.refresh_from_db()
        self.assertFalse(theirs.is_read, "marking mine read also read someone else's")

    def test_the_bell_is_not_gated_on_a_module_tick(self):
        """
        Being told your own leave was approved must not require holding the
        leave permission — the requester is usually the one person who does
        not have it.
        """
        _notify(self.org, self.other, "Your leave was approved")
        res = self.other_client.get("/api/v1/notifications/")
        self.assertEqual(res.status_code, 200)
        titles = _titles(res)
        self.assertIn("Your leave was approved", titles)

    def test_notifications_are_read_only_over_the_api(self):
        """Raised by the system, never posted by a client."""
        res = self.owner_client.post("/api/v1/notifications/", {
            "title": "Forged", "category": "leave",
        }, format="json")
        self.assertIn(res.status_code, (403, 405))


class NotificationPreferenceTests(TestCase):
    def setUp(self):
        self.owner = _make_user("pref_owner@example.com")
        self.org = _make_org(self.owner, "Pref Org")
        self.client = _auth_client(self.owner, self.org)

    def test_defaults_are_email_off_for_every_category(self):
        """Nobody gets emailed without asking."""
        res = self.client.get("/api/v1/notifications/preferences/mine/")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data, "no categories returned")
        self.assertFalse(
            any(res.data.values()),
            "some category defaulted to emailing the user without opt-in",
        )

    def test_i_can_turn_email_on_for_one_category(self):
        res = self.client.put(
            "/api/v1/notifications/preferences/mine/", {"leave": True}, format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data["leave"])
        self.assertFalse(res.data["sales"], "turning on leave turned on everything")
        self.assertTrue(
            NotificationPreference.objects.filter(
                organisation=self.org, category="leave", email_enabled=True,
            ).exists(),
        )

    def test_unknown_categories_are_ignored_not_stored(self):
        res = self.client.put(
            "/api/v1/notifications/preferences/mine/",
            {"not_a_real_category": True}, format="json",
        )
        self.assertEqual(res.status_code, 200)
        self.assertFalse(
            NotificationPreference.objects.filter(category="not_a_real_category").exists(),
        )

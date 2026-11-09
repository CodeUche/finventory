"""check_approval's sole-approver self-approval path used to swallow a failed
audit-log write (`except Exception: pass`) and return True anyway — the
approval would succeed with no audit trail, exactly the unaccountable
self-approval this module exists to prevent. It now raises, so the approval
fails too.
"""

from unittest.mock import patch

from django.test import TestCase

from apps.accounting.tests import _make_org, _make_user
from apps.core.approvals import SELF_APPROVED_NOTE, check_approval
from apps.core.models import AuditLog


class SelfApprovalAuditTests(TestCase):
    def setUp(self):
        self.user = _make_user("sole-approver@example.com")
        self.org = _make_org(self.user, "Sole Approver Org")

    def test_sole_approver_self_approval_succeeds_and_is_audited(self):
        result = check_approval(
            self.org, self.user, self.user, "journal",
            object_id="je-1", model_name="JournalEntry",
        )
        self.assertTrue(result)
        entry = AuditLog.objects.filter(
            organisation_id=self.org.id, model_name="JournalEntry", object_id="je-1",
        ).get()
        self.assertEqual(entry.object_repr, SELF_APPROVED_NOTE)

    def test_self_approval_fails_when_the_audit_write_fails(self):
        with patch("apps.core.models.AuditLog.log", side_effect=Exception("db down")):
            with self.assertRaises(ValueError):
                check_approval(
                    self.org, self.user, self.user, "journal",
                    object_id="je-2", model_name="JournalEntry",
                )
        self.assertFalse(
            AuditLog.objects.filter(organisation_id=self.org.id, object_id="je-2").exists()
        )

    def test_approval_by_someone_other_than_the_creator_is_unaffected(self):
        other = _make_user("other-approver@example.com")
        self.assertFalse(check_approval(self.org, self.user, other, "journal"))

"""
Permission overrides must not drop the owner's module tick.

DRF replaces the class-level permission_classes wholesale when a viewset
overrides get_permissions() or an @action sets its own permission_classes. Several
overrides listed only role classes, so the per-person module tick (requires_module)
silently stopped applying to those endpoints.

Two layers here:
  * behaviour tests for each override that was fixed
  * a source scan (AST) that fails when a new override omits the tick again
"""

import ast
import glob
import os
import uuid

from django.test import TestCase

from apps.core.test_module_access import _member
from apps.payroll.test_track_a import _make_org, _make_user

APPS_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

# Names that are module-tick permission classes in the view modules.
TICK_NAMES = ("_Mod", "_HRAccess", "_LeaveAccess")
# Owner/admin-only overrides need no tick: owners and admins bypass every tick,
# so adding one would change nothing.
ADMIN_ONLY = "IsOwnerOrAdmin"


def _has_tick(text):
    return any(name in text for name in TICK_NAMES)


def _scan():
    """Yield (file, class, member, lineno) for each override that drops the class tick."""
    offenders = []
    for path in sorted(glob.glob(os.path.join(APPS_DIR, "*", "views*.py"))):
        src = open(path, encoding="utf-8").read()
        tree = ast.parse(src)
        for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            class_has_tick = False
            for node in cls.body:
                if isinstance(node, ast.Assign) and any(
                    getattr(t, "id", "") == "permission_classes" for t in node.targets
                ):
                    class_has_tick = _has_tick(ast.get_source_segment(src, node) or "")
            if not class_has_tick:
                continue
            for fn in (n for n in cls.body if isinstance(n, ast.FunctionDef)):
                decorators = "".join(ast.get_source_segment(src, d) or "" for d in fn.decorator_list)
                if fn.name == "get_permissions":
                    text = ast.get_source_segment(src, fn) or ""
                elif "permission_classes" in decorators:
                    text = decorators
                else:
                    continue
                if ADMIN_ONLY in text:
                    continue
                if not _has_tick(text):
                    offenders.append((os.path.relpath(path, APPS_DIR), cls.name, fn.name, fn.lineno))
    return offenders


class OverrideScanTests(TestCase):
    def test_no_override_drops_the_module_tick(self):
        offenders = _scan()
        self.assertEqual(
            offenders, [],
            "These get_permissions / @action(permission_classes=...) overrides replace the "
            "class permissions without the module tick (add the _ModAccess_* class, or use "
            "IsOwnerOrAdmin if the action is owner/admin only): %s" % offenders,
        )

    def test_scanner_actually_detects_a_missing_tick(self):
        """Guard the guard: a synthetic offender must be reported."""
        sample = (
            "class V:\n"
            "    permission_classes = [IsAuthenticated, _ModAccess_x]\n"
            "    @action(detail=False, permission_classes=[IsAuthenticated, IsManager])\n"
            "    def boom(self, request): pass\n"
        )
        tree = ast.parse(sample)
        cls = tree.body[0]
        fn = cls.body[1]
        text = "".join(ast.get_source_segment(sample, d) for d in fn.decorator_list)
        self.assertFalse(_has_tick(text))
        self.assertTrue(_has_tick(ast.get_source_segment(sample, cls.body[0])))


class FixedOverridesBehaviourTests(TestCase):
    """Without the tick -> 403 (decided before the object lookup); with it -> past the gate."""

    def setUp(self):
        from apps.accounting.tests import _upgrade_to_business

        self.owner = _make_user("ov_owner@example.com")
        self.org = _make_org(self.owner, "Override Org")
        _upgrade_to_business(self.org)
        self.missing = uuid.uuid4()

    def _pair(self, tag, role, module, level="edit"):
        _, none, _ = _member(self.org, f"ov_{tag}_none@example.com", role)
        _, ticked, _ = _member(self.org, f"ov_{tag}_yes@example.com", role, module, level)
        return none, ticked

    def test_sales_invoice_actions(self):
        for action in ("pay_split", "void", "process_return", "confirm_proforma",
                       "fulfill", "send_email", "extend_due_date"):
            none, ticked = self._pair(f"s_{action}", "staff", "sales", "write")
            url = f"/api/v1/sales/invoices/{self.missing}/{action}/"
            with self.subTest(action=action):
                self.assertEqual(none.post(url, {}, format="json").status_code, 403)
                # Past the gate: the unknown invoice is a 404 (confirm_proforma
                # wraps its own lookup and answers 422), never a 403.
                self.assertIn(ticked.post(url, {}, format="json").status_code, (404, 422))

    def test_sales_void_and_pay_split_now_refuse_low_roles(self):
        """These two had only IsAuthenticated: a viewer could void an invoice."""
        _, viewer, _ = _member(self.org, "ov_viewer@example.com", "viewer", "sales", "edit")
        for action in ("void", "pay_split"):
            with self.subTest(action=action):
                url = f"/api/v1/sales/invoices/{self.missing}/{action}/"
                self.assertEqual(viewer.post(url, {}, format="json").status_code, 403)

    def test_owner_and_admin_unaffected_on_invoice_actions(self):
        from apps.payroll.test_track_a import _auth_client
        _, admin, _ = _member(self.org, "ov_admin@example.com", "admin")
        for client in (_auth_client(self.owner, self.org), admin):
            url = f"/api/v1/sales/invoices/{self.missing}/void/"
            self.assertEqual(client.post(url, {}, format="json").status_code, 404)

    def test_quote_send_email(self):
        none, ticked = self._pair("q", "staff", "quotes", "write")
        url = f"/api/v1/quotes/{self.missing}/send_email/"
        self.assertEqual(none.post(url, {}, format="json").status_code, 403)
        self.assertEqual(ticked.post(url, {}, format="json").status_code, 404)

    def test_period_close_checklist(self):
        none, ticked = self._pair("p", "accountant", "accounting", "view")
        url = f"/api/v1/accounting/periods/{self.missing}/close_checklist/"
        self.assertEqual(none.get(url).status_code, 403)
        self.assertEqual(ticked.get(url).status_code, 404)

    def test_employee_loan_create_needs_the_hr_tick(self):
        none, ticked = self._pair("l", "manager", "payroll", "write")
        url = "/api/v1/payroll/loans/"
        self.assertEqual(none.post(url, {}, format="json").status_code, 403)
        # Past the gate: an empty body is a validation error (400), not 403.
        self.assertNotEqual(ticked.post(url, {}, format="json").status_code, 403)

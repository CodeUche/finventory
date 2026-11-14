"""
Permission overrides must not drop the owner's module tick.

DRF replaces the class-level permission_classes wholesale when a viewset
overrides get_permissions() or an @action sets its own permission_classes. Several
overrides listed only role classes, so the per-person module tick (requires_module)
silently stopped applying to those endpoints.

Two layers here:
  * behaviour tests for each override that was fixed
  * a source scan (AST) that fails when an override drops the tick again.

The scanner is a pure function of source text (scan_source) so its own tests can
feed it synthetic offenders and prove it really detects them.
"""

import ast
import glob
import os
import tempfile
import uuid

from django.test import TestCase

from apps.core.test_module_access import _member
from apps.payroll.test_track_a import _make_user, _make_org

APPS_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

# Every permission class that stands for a per-person module tick. Anything that
# is assigned from requires_module(...) in a views file must be listed here
# (see ModuleTickAliasTests), so a renamed alias cannot slip past the scanner.
TICK_NAMES = {
    "_HRAccess", "_LeaveAccess",
    "_ModAccess_accounting", "_ModAccess_bills", "_ModAccess_budgets",
    "_ModAccess_customers", "_ModAccess_expenses", "_ModAccess_inventory",
    "_ModAccess_purchases", "_ModAccess_quotes", "_ModAccess_recurring",
    "_ModAccess_reports", "_ModAccess_sales", "_ModAccess_suppliers",
    "_ModAccess_tax",
}
# Owner/admin-only overrides need no tick: owners and admins bypass every tick,
# so adding one would change nothing. Judged per list element (never by substring).
ADMIN_ONLY = "IsOwnerOrAdmin"


def view_files(root=APPS_DIR):
    """Every views module, recursively: views.py, modifier_views.py, till_views.py ..."""
    return sorted(glob.glob(os.path.join(root, "**", "*views*.py"), recursive=True))


def _names(node):
    """All identifiers (Name ids, and requires_module call heads) inside an expression."""
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _is_ticked(node):
    names = _names(node)
    return bool(names & TICK_NAMES) or "requires_module" in names


def _is_ok(node):
    """An expression that lists a tick, or is owner/admin only."""
    names = _names(node)
    return _is_ticked(node) or ADMIN_ONLY in names


def _class_permission_expr(cls):
    for node in cls.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "permission_classes" for t in node.targets):
                return node.value
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "permission_classes" and node.value:
                return node.value
    return None


def _collect_classes(tree):
    """All classes, including nested ones."""
    return [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]


def _own_tick_map(classes):
    """class name -> True/False for 'declares a ticked permission_classes itself'."""
    out = {}
    for cls in classes:
        expr = _class_permission_expr(cls)
        if expr is not None:
            out[cls.name] = out.get(cls.name, False) or _is_ticked(expr)
    return out


def _has_tick(cls, by_name, own, seen=None):
    """Own declaration wins; otherwise inherit from the first base that declares one."""
    seen = seen or set()
    if cls.name in seen:
        return False
    seen.add(cls.name)
    if cls.name in own:
        return own[cls.name]
    for base in cls.bases:
        base_name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", None)
        base_cls = by_name.get(base_name)
        if base_cls is not None and _has_tick(base_cls, by_name, own, seen):
            return True
    return False


def _returns(fn):
    """Return statements of fn itself (not of nested functions/classes)."""
    out, stack = [], list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Return):
            out.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return out


def _is_super_get_permissions(value):
    """`return super().get_permissions()` keeps the class permissions."""
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Attribute)
        and value.func.attr == "get_permissions"
        and isinstance(value.func.value, ast.Call)
        and isinstance(value.func.value.func, ast.Name)
        and value.func.value.func.id == "super"
    )


def scan_source(src, path="<memory>", extra_classes=None):
    """Offenders in one module's source: (path, class, member, lineno).

    A class is checked when it (or a base class it inherits from, in this module
    or among `extra_classes`) declares a ticked permission_classes. For those:
      * every @action(permission_classes=...) must list a tick (or IsOwnerOrAdmin)
      * every return branch of get_permissions must list a tick (or IsOwnerOrAdmin),
        or defer to super().get_permissions()
    """
    tree = ast.parse(src)
    classes = _collect_classes(tree)
    pool = list(classes) + list(extra_classes or [])
    by_name = {c.name: c for c in pool}
    own = _own_tick_map(pool)
    offenders = []
    for cls in classes:
        if not _has_tick(cls, by_name, own):
            continue
        for fn in (n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
            if fn.name == "get_permissions":
                for ret in _returns(fn):
                    if ret.value is None or _is_super_get_permissions(ret.value):
                        continue
                    if not _is_ok(ret.value):
                        offenders.append((path, cls.name, f"get_permissions@L{ret.lineno}", ret.lineno))
                continue
            for dec in fn.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                for kw in dec.keywords:
                    if kw.arg == "permission_classes" and not _is_ok(kw.value):
                        offenders.append((path, cls.name, fn.name, fn.lineno))
    return offenders


def scan_tree(root=APPS_DIR):
    parsed = {}
    for path in view_files(root):
        with open(path, encoding="utf-8") as fh:
            parsed[path] = fh.read()
    # Classes from every module, so a tick inherited from a base/mixin in another
    # file is still seen.
    all_classes = []
    for src in parsed.values():
        all_classes.extend(_collect_classes(ast.parse(src)))
    offenders = []
    for path, src in parsed.items():
        offenders.extend(scan_source(src, os.path.relpath(path, root), extra_classes=all_classes))
    return offenders


class OverrideScanTests(TestCase):
    def test_no_override_drops_the_module_tick(self):
        offenders = scan_tree()
        self.assertEqual(
            offenders, [],
            "These get_permissions / @action(permission_classes=...) overrides replace the "
            "class permissions without the module tick (add the _ModAccess_* class, or use "
            "IsOwnerOrAdmin if the action is owner/admin only): %s" % offenders,
        )

    def test_scan_covers_the_secondary_views_modules(self):
        names = {os.path.basename(p) for p in view_files()}
        for expected in ("modifier_views.py", "till_views.py", "import_views.py", "ess_views.py", "views.py"):
            self.assertIn(expected, names)

    def test_every_requires_module_alias_is_a_known_tick_name(self):
        """A new alias must be added to TICK_NAMES or the scan could not recognise it."""
        found = set()
        for path in view_files():
            tree = ast.parse(open(path, encoding="utf-8").read())
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Assign)
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == "requires_module"
                ):
                    found.update(t.id for t in node.targets if isinstance(t, ast.Name))
        self.assertEqual(found - TICK_NAMES, set())


class ScannerDetectsOffendersTests(TestCase):
    """Guard the guard: each synthetic offender must be reported, each clean one passed."""

    def _scan(self, src):
        return scan_source(src, "synthetic_views.py")

    def test_action_missing_the_tick_is_reported(self):
        offenders = self._scan(
            "class V:\n"
            "    permission_classes = [IsAuthenticated, _ModAccess_sales]\n"
            "    @action(detail=False, permission_classes=[IsAuthenticated, IsManager])\n"
            "    def boom(self, request): pass\n"
        )
        self.assertEqual([(o[1], o[2]) for o in offenders], [("V", "boom")])

    def test_action_with_tick_or_admin_only_is_clean(self):
        self.assertEqual(self._scan(
            "class V:\n"
            "    permission_classes = [IsAuthenticated, _ModAccess_sales]\n"
            "    @action(permission_classes=[IsAuthenticated, IsManager, _ModAccess_sales])\n"
            "    def a(self, request): pass\n"
            "    @action(permission_classes=[IsAuthenticated, IsOwnerOrAdmin])\n"
            "    def b(self, request): pass\n"
        ), [])

    def test_mixed_branch_get_permissions_reports_the_bad_branch(self):
        offenders = self._scan(
            "class V:\n"
            "    permission_classes = [IsAuthenticated, _ModAccess_sales]\n"
            "    def get_permissions(self):\n"
            "        if self.action == 'destroy':\n"
            "            return [IsAuthenticated(), IsManager(), _ModAccess_sales()]\n"
            "        return [IsAuthenticated(), IsStaff()]\n"
        )
        self.assertEqual(len(offenders), 1)
        self.assertEqual(offenders[0][1], "V")
        self.assertEqual(offenders[0][3], 6)

    def test_admin_only_name_in_one_branch_does_not_clear_the_other(self):
        offenders = self._scan(
            "class V:\n"
            "    permission_classes = [IsAuthenticated, _ModAccess_sales]\n"
            "    def get_permissions(self):\n"
            "        if self.action == 'lock':\n"
            "            return [IsAuthenticated(), IsOwnerOrAdmin()]\n"
            "        return [IsAuthenticated(), IsStaff()]\n"
        )
        self.assertEqual(len(offenders), 1)

    def test_lookalike_name_is_not_a_tick(self):
        offenders = self._scan(
            "class V:\n"
            "    permission_classes = [IsAuthenticated, _ModAccess_sales]\n"
            "    @action(permission_classes=[IsAuthenticated, IsOwnerOrAdminOrNothing])\n"
            "    def a(self, request): pass\n"
        )
        self.assertEqual(len(offenders), 1)

    def test_super_get_permissions_is_clean(self):
        self.assertEqual(self._scan(
            "class V:\n"
            "    permission_classes = [IsAuthenticated, _ModAccess_sales]\n"
            "    def get_permissions(self):\n"
            "        if self.action == 'x':\n"
            "            return [IsAuthenticated(), IsManager(), _ModAccess_sales()]\n"
            "        return super().get_permissions()\n"
        ), [])

    def test_tick_inherited_from_a_base_class_is_scanned(self):
        offenders = self._scan(
            "class Base:\n"
            "    permission_classes = [IsAuthenticated, _ModAccess_inventory]\n"
            "class Child(Base):\n"
            "    @action(permission_classes=[IsAuthenticated, IsManager])\n"
            "    def boom(self, request): pass\n"
        )
        self.assertEqual([(o[1], o[2]) for o in offenders], [("Child", "boom")])

    def test_tick_inherited_from_a_base_in_another_file_is_scanned(self):
        base = ast.parse(
            "class Base:\n    permission_classes = [IsAuthenticated, _ModAccess_inventory]\n"
        ).body
        offenders = scan_source(
            "class Child(Base):\n"
            "    def get_permissions(self):\n"
            "        return [IsAuthenticated(), IsStaff()]\n",
            "other_views.py", extra_classes=base,
        )
        self.assertEqual(len(offenders), 1)

    def test_annotated_permission_classes_are_recognised(self):
        offenders = self._scan(
            "class V:\n"
            "    permission_classes: list = [IsAuthenticated, _ModAccess_sales]\n"
            "    @action(permission_classes=[IsAuthenticated])\n"
            "    def boom(self, request): pass\n"
        )
        self.assertEqual(len(offenders), 1)

    def test_nested_classes_are_scanned(self):
        offenders = self._scan(
            "def factory():\n"
            "    class V:\n"
            "        permission_classes = [IsAuthenticated, _HRAccess]\n"
            "        @action(permission_classes=[IsAuthenticated, IsManager])\n"
            "        def boom(self, request): pass\n"
            "    return V\n"
            "class Outer:\n"
            "    class Inner:\n"
            "        permission_classes = [IsAuthenticated, _ModAccess_tax]\n"
            "        def get_permissions(self):\n"
            "            return [IsAuthenticated()]\n"
        )
        self.assertEqual(sorted(o[1] for o in offenders), ["Inner", "V"])

    def test_class_without_any_tick_is_not_judged(self):
        self.assertEqual(self._scan(
            "class V:\n"
            "    permission_classes = [IsAuthenticated, IsStaff]\n"
            "    @action(permission_classes=[IsAuthenticated])\n"
            "    def a(self, request): pass\n"
        ), [])

    def test_a_star_views_file_is_found_and_scanned(self):
        with tempfile.TemporaryDirectory() as root:
            sub = os.path.join(root, "myapp")
            os.makedirs(sub)
            with open(os.path.join(sub, "till_views.py"), "w", encoding="utf-8") as fh:
                fh.write(
                    "class V:\n"
                    "    permission_classes = [IsAuthenticated, _ModAccess_sales]\n"
                    "    @action(permission_classes=[IsAuthenticated, IsStaff])\n"
                    "    def boom(self, request): pass\n"
                )
            with open(os.path.join(sub, "helpers.py"), "w", encoding="utf-8") as fh:
                fh.write("x = 1\n")
            offenders = scan_tree(root)
        self.assertEqual([(o[0], o[1], o[2]) for o in offenders],
                         [(os.path.join("myapp", "till_views.py"), "V", "boom")])


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
        for action in ("pay_split", "process_return", "confirm_proforma",
                       "fulfill", "send_email", "extend_due_date"):
            none, ticked = self._pair(f"s_{action}", "staff", "sales", "write")
            url = f"/api/v1/sales/invoices/{self.missing}/{action}/"
            with self.subTest(action=action):
                self.assertEqual(none.post(url, {}, format="json").status_code, 403)
                # Past the gate: the unknown invoice is a 404 (confirm_proforma
                # wraps its own lookup and answers 422), never a 403.
                self.assertIn(ticked.post(url, {}, format="json").status_code, (404, 422))

    def test_void_needs_edit_level_not_write(self):
        url = f"/api/v1/sales/invoices/{self.missing}/void/"
        _, none, _ = _member(self.org, "ov_v_none@example.com", "staff")
        _, view, _ = _member(self.org, "ov_v_view@example.com", "staff", "sales", "view")
        _, write, _ = _member(self.org, "ov_v_write@example.com", "staff", "sales", "write")
        _, edit, _ = _member(self.org, "ov_v_edit@example.com", "staff", "sales", "edit")
        _, wrong, _ = _member(self.org, "ov_v_wrong@example.com", "staff", "quotes", "edit")
        for label, client in (("none", none), ("view", view), ("write", write), ("wrong", wrong)):
            with self.subTest(level=label):
                self.assertEqual(client.post(url, {}, format="json").status_code, 403)
        # Edit passes the gate: the unknown invoice is a 404.
        self.assertEqual(edit.post(url, {}, format="json").status_code, 404)

    def test_void_message_is_plain(self):
        url = f"/api/v1/sales/invoices/{self.missing}/void/"
        _, write, _ = _member(self.org, "ov_vm@example.com", "staff", "sales", "write")
        body = write.post(url, {}, format="json").content.decode()
        self.assertIn("full edit access", body)

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
            for action in ("void", "pay_split"):
                url = f"/api/v1/sales/invoices/{self.missing}/{action}/"
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

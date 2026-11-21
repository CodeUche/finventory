"""
Editing the amounts of an invoice raised in an EARLIER month: the reversal of the
old entry belongs to that same month (not today's), so each period ends at the
right figures. A locked earlier month refuses the edit and changes nothing.
"""

from collections import defaultdict
from datetime import date

from apps.accounting.models import FinancialPeriod, JournalLine
from apps.sales.test_new_sale_and_invoice import D, URL
from apps.sales.test_sales_ledger import LedgerBase


def _first_of_previous_month():
    t = date.today()
    return date(t.year - 1, 12, 1) if t.month == 1 else date(t.year, t.month - 1, 1)


class RepostAcrossPeriodsTests(LedgerBase):
    def per_period(self):
        """{(year, month): {role: net debit}} over every posted line."""
        out = defaultdict(lambda: defaultdict(lambda: D("0")))
        roles = ("cash", "ar", "deposits", "vat", "revenue", "cogs", "inventory")
        ids = {self.acct(r).id: r for r in roles}
        for ln in JournalLine.objects.filter(journal_entry__organisation=self.org).select_related("journal_entry"):
            role = ids.get(ln.account_id)
            if role:
                d = ln.journal_entry.entry_date
                out[(d.year, d.month)][role] += ln.debit - ln.credit
        return out

    def edit(self, inv, qty=1):
        return self.api.patch(f"{URL}{inv.id}/edit_lines/", {
            "items": [{"product_id": str(self.taxed.id), "quantity": qty, "unit_price": "1000"}]}, format="json")

    def setUp(self):
        super().setUp()
        self.early = _first_of_previous_month()
        today = date.today()
        self.now_key = (today.year, today.month)
        self.early_key = (self.early.year, self.early.month)

    def test_an_earlier_open_month_ends_at_the_new_figures_and_this_month_nets_to_zero(self):
        inv = self.sale(payment_method="credit", amount_paid="0", issue_date=self.early.isoformat())
        self.assertEqual(self.edit(inv).status_code, 200)             # 2 x 1000 -> 1 x 1000
        p = self.per_period()
        self.assertEqual(p[self.early_key]["revenue"], D("-1000"))
        self.assertEqual(p[self.early_key]["vat"], D("-75"))
        self.assertEqual(p[self.early_key]["ar"], D("1075"))
        self.assertEqual(p[self.early_key]["cogs"], D("600"))
        for role, v in p[self.now_key].items():
            self.assertEqual(v, D("0"), f"{role} should net to 0 in the current month")

    def test_an_earlier_locked_month_refuses_the_edit_and_changes_nothing(self):
        inv = self.sale(payment_method="credit", amount_paid="0", issue_date=self.early.isoformat())
        FinancialPeriod.objects.create(organisation=self.org, year=self.early.year, month=self.early.month,
                                       is_locked=True)
        before = self.per_period()
        res = self.edit(inv)
        self.assertEqual(res.status_code, 422)
        self.assertIn("locked", res.data["error"].lower())
        inv.refresh_from_db()
        self.assertEqual(inv.total_amount, D("2150"))
        self.assertEqual(self.on_hand(self.taxed), D("98"))
        self.assertEqual({k: dict(v) for k, v in self.per_period().items()}, {k: dict(v) for k, v in before.items()})

    def test_a_same_day_edit_keeps_everything_in_the_one_month(self):
        inv = self.sale(payment_method="credit", amount_paid="0")
        self.assertEqual(self.edit(inv).status_code, 200)
        p = self.per_period()
        self.assertEqual(list(p.keys()), [self.now_key])
        self.assertEqual((p[self.now_key]["revenue"], p[self.now_key]["vat"]), (D("-1000"), D("-75")))

    def test_void_after_a_cross_period_edit_nets_to_zero_in_total_and_lands_in_this_month(self):
        inv = self.sale(payment_method="credit", amount_paid="0", issue_date=self.early.isoformat())
        self.edit(inv)
        self.assertEqual(self.api.post(f"{URL}{inv.id}/void/").status_code, 200)
        p = self.per_period()
        for role in ("revenue", "vat", "ar", "cogs"):
            total = sum((p[k][role] for k in p), D("0"))
            self.assertEqual(total, D("0"), role)
        # the accepted rule for voids: they unwind in the current period
        self.assertEqual(p[self.now_key]["revenue"], D("1000"))
        self.assertEqual(p[self.early_key]["revenue"], D("-1000"))

    def test_a_second_edit_across_periods_stays_correct(self):
        inv = self.sale(payment_method="credit", amount_paid="0", issue_date=self.early.isoformat())
        self.edit(inv, qty=1)
        self.edit(inv, qty=3)
        p = self.per_period()
        self.assertEqual(p[self.early_key]["revenue"], D("-3000"))
        self.assertEqual(p[self.early_key]["vat"], D("-225"))
        for role, v in p[self.now_key].items():
            self.assertEqual(v, D("0"), role)

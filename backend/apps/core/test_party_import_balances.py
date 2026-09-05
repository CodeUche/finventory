"""
CSV import of customers and suppliers WITH the balances they already carry —
the reviewer's "import customer with or without balances" request, mirrored for
suppliers.

The three optional columns (opening_balance, opening_balance_date,
opening_balance_side) route through exactly the same services the per-party
"Adjust Opening Balance" action uses, so an imported take-on is posted to the
ledger identically to a hand-keyed one, and re-importing a corrected file fixes
the balance in place instead of stacking a second entry on top of the first.
"""

from decimal import Decimal

from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.tenancy.services import OrganisationService
from apps.customers.models import Customer
from apps.suppliers.models import Supplier
from apps.accounting.models import JournalEntry


def _make_user(email="party_import@example.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="Party", last_name="Importer", is_verified=True,
    )


def _make_org(user, name="Party Import Org"):
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


def _csv(text: str, name="import.csv"):
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


class _PartyImportBase(TestCase):
    party_kind = ""

    def setUp(self):
        self.user = _make_user()
        self.org = _make_org(self.user)
        self.client = _auth_client(self.user, self.org)

    def _post(self, url, text):
        return self.client.post(url, {"file": _csv(text)}, format="multipart")

    def _take_on_entries(self, party_id):
        return JournalEntry.objects.filter(
            organisation=self.org,
            source_type="opening_balance",
            source_ref__startswith=f"opening-{self.party_kind}-{party_id}",
            status="posted",
        )


class CustomerImportWithBalancesTests(_PartyImportBase):
    party_kind = "customer"
    URL = "/api/v1/import/customers/"

    def test_import_without_balances_still_works_untouched(self):
        """The original behaviour — no balance columns at all."""
        res = self._post(self.URL, "code,name\nC001,Adaeze Okafor\n")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["created"], 1)
        self.assertEqual(res.data["balances_set"], 0)
        cust = Customer.objects.get(organisation=self.org, code="C001")
        self.assertEqual(Decimal(str(cust.outstanding_balance)), Decimal("0"))
        self.assertIsNone(cust.opening_balance_date)

    def test_blank_balance_column_posts_nothing(self):
        """A file that HAS the column but leaves it empty must not post."""
        res = self._post(self.URL, "code,name,opening_balance\nC002,Empty Balance,\n")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["balances_set"], 0)
        cust = Customer.objects.get(organisation=self.org, code="C002")
        self.assertEqual(self._take_on_entries(cust.id).count(), 0)

    def test_import_with_debit_balance_posts_a_take_on(self):
        res = self._post(
            self.URL,
            "code,name,opening_balance,opening_balance_date,opening_balance_side\n"
            "C003,Zenith Foods,250000,2026-01-01,DR\n",
        )
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["balances_set"], 1)
        cust = Customer.objects.get(organisation=self.org, code="C003")
        # Positive = the customer owes us.
        self.assertEqual(Decimal(str(cust.outstanding_balance)), Decimal("250000"))
        self.assertEqual(str(cust.opening_balance_date), "2026-01-01")
        self.assertEqual(self._take_on_entries(cust.id).count(), 1)

    def test_side_defaults_to_debit_for_customers(self):
        """Most imported debtors owe us — omitting the side must assume that."""
        res = self._post(self.URL, "code,name,opening_balance\nC004,No Side,90000\n")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        cust = Customer.objects.get(organisation=self.org, code="C004")
        self.assertEqual(Decimal(str(cust.outstanding_balance)), Decimal("90000"))

    def test_credit_balance_flips_the_sign(self):
        """A customer in credit (prepaid) carries a negative balance."""
        res = self._post(
            self.URL,
            "code,name,opening_balance,opening_balance_side\nC005,Prepaid Co,40000,CR\n",
        )
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        cust = Customer.objects.get(organisation=self.org, code="C005")
        self.assertEqual(Decimal(str(cust.outstanding_balance)), Decimal("-40000"))

    def test_negative_amount_is_read_as_the_other_side(self):
        """Exported ledgers often use a minus sign instead of a CR marker."""
        res = self._post(self.URL, "code,name,opening_balance\nC006,Minus Co,-40000\n")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        cust = Customer.objects.get(organisation=self.org, code="C006")
        self.assertEqual(Decimal(str(cust.outstanding_balance)), Decimal("-40000"))

    def test_reimporting_a_corrected_file_replaces_rather_than_doubles(self):
        """The whole point of routing through the service: idempotency."""
        row = "code,name,opening_balance,opening_balance_side\nC007,Fix Me,{amt},DR\n"
        self._post(self.URL, row.format(amt="100000"))
        cust = Customer.objects.get(organisation=self.org, code="C007")
        self.assertEqual(Decimal(str(cust.outstanding_balance)), Decimal("100000"))

        self._post(self.URL, row.format(amt="150000"))
        cust.refresh_from_db()
        # Corrected in place — NOT 100k + 150k.
        self.assertEqual(Decimal(str(cust.outstanding_balance)), Decimal("150000"))
        # The old entry is reversed, not deleted, so the audit trail survives.
        self.assertGreaterEqual(self._take_on_entries(cust.id).count(), 1)

    def test_bad_side_is_reported_and_the_customer_still_imports(self):
        res = self._post(
            self.URL,
            "code,name,opening_balance,opening_balance_side\nC008,Bad Side,5000,XX\n",
        )
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["created"], 1)
        self.assertEqual(res.data["balances_set"], 0)
        self.assertTrue(any(e["field"] == "opening_balance_side" for e in res.data["errors"]))
        cust = Customer.objects.get(organisation=self.org, code="C008")
        self.assertEqual(Decimal(str(cust.outstanding_balance)), Decimal("0"))

    def test_bad_date_is_reported_and_no_balance_is_posted(self):
        res = self._post(
            self.URL,
            "code,name,opening_balance,opening_balance_date\nC009,Bad Date,5000,not-a-date\n",
        )
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["balances_set"], 0)
        self.assertTrue(any(e["field"] == "opening_balance_date" for e in res.data["errors"]))

    def test_template_download_offers_the_new_columns(self):
        res = self.client.get("/api/v1/import/template/customers/")
        self.assertEqual(res.status_code, 200)
        header = res.content.decode("utf-8").splitlines()[0]
        for col in ("opening_balance", "opening_balance_date", "opening_balance_side"):
            self.assertIn(col, header)


class SupplierImportWithBalancesTests(_PartyImportBase):
    party_kind = "supplier"
    URL = "/api/v1/import/suppliers/"

    def test_import_without_balances_still_works_untouched(self):
        # Two columns, not one: _parse_csv deliberately skips any row with
        # fewer than two filled cells (it exists to ignore section headers in
        # exported spreadsheets), so a one-column file imports nothing. That
        # is long-standing behaviour shared by every import and unrelated to
        # opening balances, so it is left alone here.
        res = self._post(self.URL, "name,code\nABC Distributors Ltd,ABC-001\n")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["created"], 1)
        self.assertEqual(res.data["balances_set"], 0)

    def test_side_defaults_to_credit_for_suppliers(self):
        """A supplier balance normally runs the other way — we owe them."""
        res = self._post(
            self.URL,
            "name,code,opening_balance,opening_balance_date\n"
            "Kobo Trading,KOB-001,180000,2026-01-01\n",
        )
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["balances_set"], 1)
        sup = Supplier.objects.get(organisation=self.org, code="KOB-001")
        self.assertEqual(Decimal(str(sup.opening_balance)), Decimal("180000"))
        self.assertEqual(str(sup.opening_balance_date), "2026-01-01")
        self.assertEqual(self._take_on_entries(sup.id).count(), 1)

    def test_explicit_debit_side_is_honoured(self):
        """A supplier we have overpaid sits the other way round."""
        res = self._post(
            self.URL,
            "name,code,opening_balance,opening_balance_side\nOverpaid Ltd,OVR-001,25000,DR\n",
        )
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        sup = Supplier.objects.get(organisation=self.org, code="OVR-001")
        self.assertEqual(Decimal(str(sup.opening_balance)), Decimal("-25000"))

    def test_reimporting_a_corrected_file_replaces_rather_than_doubles(self):
        row = "name,code,opening_balance\nFix Supplier,FIX-001,{amt}\n"
        self._post(self.URL, row.format(amt="80000"))
        self._post(self.URL, row.format(amt="95000"))
        sup = Supplier.objects.get(organisation=self.org, code="FIX-001")
        self.assertEqual(Decimal(str(sup.opening_balance)), Decimal("95000"))

    def test_template_download_offers_the_new_columns(self):
        res = self.client.get("/api/v1/import/template/suppliers/")
        self.assertEqual(res.status_code, 200)
        header = res.content.decode("utf-8").splitlines()[0]
        for col in ("opening_balance", "opening_balance_date", "opening_balance_side"):
            self.assertIn(col, header)

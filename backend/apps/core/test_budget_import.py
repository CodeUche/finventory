"""
CSV import of Budgets — B5. One row per BUDGET LINE; rows sharing the same
(budget_name, fiscal_year) pair group into a single multi-line budget, with
header fields (budget_type, notes) taken from that budget's first row only.
Create-only: an existing (budget_name, fiscal_year) pair is left untouched,
since a Budget already has its own edit screen (including the monthly grid)
that this importer must not disturb.
"""

from decimal import Decimal

from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounting.tests import _upgrade_to_business
from apps.accounting.models import Account
from apps.authentication.models import User
from apps.budgets.models import Budget
from apps.tenancy.services import OrganisationService


def _make_user(email="budget_import@example.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="Budget", last_name="Importer", is_verified=True,
    )


def _make_org(user, name="Budget Import Org"):
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


def _csv(text: str, name="budgets.csv"):
    return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")


class BudgetImportTests(TestCase):
    URL = "/api/v1/import/budgets/"

    def setUp(self):
        self.user = _make_user()
        self.org = _make_org(self.user)
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)

    def _post(self, url, text):
        return self.client.post(url, {"file": _csv(text)}, format="multipart")

    def test_multi_line_rows_group_into_one_budget(self):
        csv_text = (
            "budget_name,fiscal_year,category_name,category_type,budgeted_amount\n"
            "2026 Ops,2026,Sales,revenue,5000000\n"
            "2026 Ops,2026,Rent,expense,300000\n"
        )
        res = self._post(self.URL, csv_text)
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["budgets_created"], 1)
        self.assertEqual(res.data["lines_created"], 2)

        budget = Budget.objects.get(organisation=self.org, name="2026 Ops", fiscal_year=2026)
        self.assertEqual(budget.lines.count(), 2)

    def test_different_budget_keys_create_separate_budgets(self):
        csv_text = (
            "budget_name,fiscal_year,category_name,category_type,budgeted_amount\n"
            "Budget A,2026,Sales,revenue,1000\n"
            "Budget B,2026,Rent,expense,2000\n"
        )
        res = self._post(self.URL, csv_text)
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["budgets_created"], 2)
        self.assertTrue(Budget.objects.filter(organisation=self.org, name="Budget A", fiscal_year=2026).exists())
        self.assertTrue(Budget.objects.filter(organisation=self.org, name="Budget B", fiscal_year=2026).exists())

    def test_same_name_different_fiscal_year_are_separate_budgets(self):
        csv_text = (
            "budget_name,fiscal_year,category_name,category_type,budgeted_amount\n"
            "Annual Plan,2025,Sales,revenue,1000\n"
            "Annual Plan,2026,Sales,revenue,1000\n"
        )
        res = self._post(self.URL, csv_text)
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["budgets_created"], 2)

    def test_header_fields_come_from_the_first_row_of_the_group(self):
        csv_text = (
            "budget_name,fiscal_year,category_name,category_type,budgeted_amount,budget_type\n"
            "2026 Ops,2026,Sales,revenue,1000,operational\n"
            "2026 Ops,2026,Rent,expense,1000,capital\n"
        )
        res = self._post(self.URL, csv_text)
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        budget = Budget.objects.get(organisation=self.org, name="2026 Ops", fiscal_year=2026)
        self.assertEqual(budget.budget_type, "operational")

    def test_optional_columns_are_applied(self):
        account = Account.objects.filter(organisation=self.org, account_type="expense").first()
        self.assertIsNotNone(account, "COA should be auto-seeded on org creation")
        csv_text = (
            "budget_name,fiscal_year,category_name,category_type,budgeted_amount,"
            "period_month,sub_category,account_code,forecast_amount\n"
            f"2026 Ops,2026,Utilities,expense,50000,3,Electricity,{account.code},55000\n"
        )
        res = self._post(self.URL, csv_text)
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        line = Budget.objects.get(organisation=self.org, name="2026 Ops", fiscal_year=2026).lines.first()
        self.assertEqual(line.period_month, 3)
        self.assertEqual(line.sub_category, "Electricity")
        self.assertEqual(line.account_id, account.id)
        self.assertEqual(Decimal(str(line.forecast_amount)), Decimal("55000"))

    def test_existing_budget_key_is_left_untouched(self):
        existing = Budget.objects.create(organisation=self.org, name="Existing", fiscal_year=2026)
        csv_text = (
            "budget_name,fiscal_year,category_name,category_type,budgeted_amount\n"
            "Existing,2026,Sales,revenue,999999\n"
        )
        res = self._post(self.URL, csv_text)
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["budgets_created"], 0)
        self.assertTrue(any(e["field"] == "budget_name" for e in res.data["errors"]))
        existing.refresh_from_db()
        self.assertEqual(existing.lines.count(), 0)  # untouched, not appended to

    def test_invalid_category_type_reports_a_clear_error(self):
        csv_text = (
            "budget_name,fiscal_year,category_name,category_type,budgeted_amount\n"
            "Bad Type,2026,Sales,income,1000\n"
        )
        res = self._post(self.URL, csv_text)
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["budgets_created"], 0)
        self.assertTrue(any(e["field"] == "category_type" for e in res.data["errors"]))

    def test_unknown_account_code_reports_a_clear_error(self):
        csv_text = (
            "budget_name,fiscal_year,category_name,category_type,budgeted_amount,account_code\n"
            "Bad Account,2026,Sales,revenue,1000,NOPE-999\n"
        )
        res = self._post(self.URL, csv_text)
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["budgets_created"], 0)
        self.assertTrue(any(e["field"] == "account_code" for e in res.data["errors"]))

    def test_template_download_offers_the_new_columns(self):
        res = self.client.get("/api/v1/import/template/budgets/")
        self.assertEqual(res.status_code, 200)
        header = res.content.decode("utf-8").splitlines()[0]
        for col in ("budget_name", "fiscal_year", "category_name", "category_type", "budgeted_amount",
                    "period_month", "sub_category", "account_code", "forecast_amount"):
            self.assertIn(col, header)

    def test_another_organisation_does_not_see_the_imported_budget(self):
        csv_text = (
            "budget_name,fiscal_year,category_name,category_type,budgeted_amount\n"
            "Isolated,2026,Sales,revenue,1000\n"
        )
        self._post(self.URL, csv_text)

        other_user = _make_user("other_budget_import@example.com")
        other_org = _make_org(other_user, "Other Budget Import Org")
        self.assertFalse(Budget.objects.filter(organisation=other_org, name="Isolated", fiscal_year=2026).exists())

"""Tests for payroll: employee CRUD, payroll run creation."""

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.authentication.models import User
from apps.payroll.models import Employee, PayrollRun
from apps.subscriptions.models import Plan
from apps.subscriptions.services import SubscriptionService
from apps.tenancy.services import OrganisationService


def _make_user(email="pay_owner@example.com"):
    return User.objects.create_user(
        email=email, password="TestPass123!",
        first_name="Pay", last_name="Owner", is_verified=True,
    )


def _make_org(user, name="Pay Org"):
    return OrganisationService.create_organisation(
        name=name, owner=user, extra={"currency": "NGN", "country": "NG"},
    )


def _upgrade_to_business(org):
    """Upgrade org to Business plan so plan_requires('payroll') passes."""
    plan = Plan.objects.get(slug="business")
    SubscriptionService.upgrade_plan(org, plan)
    org.refresh_from_db()


def _auth_client(user, org):
    client = APIClient()
    refresh = RefreshToken.for_user(user)
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}",
        HTTP_X_ORGANISATION_ID=str(org.id),
    )
    return client


class EmployeeCRUDTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.org = _make_org(self.user)
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)

    def _payload(self, **overrides):
        base = {
            "first_name": "Alice",
            "last_name": "Johnson",
            "email": "alice@company.com",
            "phone": "08011112222",
            "department": "Finance",
            "job_title": "Accountant",
            "basic_salary": "150000.00",
            "employment_type": "full_time",
            "hire_date": "2024-01-15",
        }
        base.update(overrides)
        return base

    def test_create_employee(self):
        res = self.client.post("/api/v1/payroll/employees/", self._payload())
        self.assertEqual(res.status_code, 201, msg=str(res.data))
        self.assertTrue(Employee.objects.filter(organisation=self.org, first_name="Alice").exists())

    def test_list_employees(self):
        self.client.post("/api/v1/payroll/employees/", self._payload())
        res = self.client.get("/api/v1/payroll/employees/")
        self.assertEqual(res.status_code, 200)
        data = res.data.get("results") or res.data
        self.assertGreater(len(data), 0)

    def test_retrieve_employee(self):
        create_res = self.client.post("/api/v1/payroll/employees/", self._payload())
        self.assertEqual(create_res.status_code, 201, msg=str(create_res.data))
        eid = create_res.data["id"]
        res = self.client.get(f"/api/v1/payroll/employees/{eid}/")
        self.assertEqual(res.status_code, 200)
        # employee_id is auto-generated — just verify it's present and non-empty
        self.assertTrue(res.data.get("employee_id"))

    def test_update_employee_salary(self):
        create_res = self.client.post("/api/v1/payroll/employees/", self._payload())
        self.assertEqual(create_res.status_code, 201, msg=str(create_res.data))
        eid = create_res.data["id"]
        res = self.client.patch(f"/api/v1/payroll/employees/{eid}/", {"basic_salary": "180000.00"})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(str(res.data["basic_salary"]).startswith("180000"))

    def test_delete_employee(self):
        create_res = self.client.post("/api/v1/payroll/employees/", self._payload())
        self.assertEqual(create_res.status_code, 201, msg=str(create_res.data))
        eid = create_res.data["id"]
        res = self.client.delete(f"/api/v1/payroll/employees/{eid}/")
        self.assertIn(res.status_code, [200, 204])

    def test_cross_org_isolation(self):
        create_res = self.client.post("/api/v1/payroll/employees/", self._payload())
        self.assertEqual(create_res.status_code, 201, msg=str(create_res.data))
        eid = create_res.data["id"]
        other_user = _make_user("pay_other@example.com")
        other_org = _make_org(other_user, "Other Pay Org")
        _upgrade_to_business(other_org)   # give business plan so 403 = tenant isolation, not plan gate
        c = _auth_client(other_user, other_org)
        res = c.get(f"/api/v1/payroll/employees/{eid}/")
        self.assertIn(res.status_code, [403, 404])

    def test_search_employees(self):
        self.client.post("/api/v1/payroll/employees/", self._payload())
        res = self.client.get("/api/v1/payroll/employees/?search=Alice")
        self.assertEqual(res.status_code, 200)
        data = res.data.get("results") or res.data
        self.assertGreater(len(data), 0)


class PayrollRunTests(TestCase):
    def setUp(self):
        self.user = _make_user("run_owner@example.com")
        self.org = _make_org(self.user, "Run Org")
        _upgrade_to_business(self.org)
        self.client = _auth_client(self.user, self.org)
        # Create an employee
        self.client.post("/api/v1/payroll/employees/", {
            "first_name": "Bob",
            "last_name": "Smith",
            "email": "bob@company.com",
            "phone": "08099998888",
            "department": "Sales",
            "job_title": "Rep",
            "basic_salary": "120000.00",
            "employment_type": "full_time",
            "hire_date": "2024-03-01",
        })

    def test_create_payroll_run(self):
        res = self.client.post("/api/v1/payroll/runs/", {
            "period_year": 2026,
            "period_month": 1,
        })
        self.assertIn(res.status_code, [200, 201], msg=str(res.data))
        self.assertTrue(
            PayrollRun.objects.filter(organisation=self.org, period_year=2026, period_month=1).exists()
        )

    def test_duplicate_payroll_run_rejected(self):
        self.client.post("/api/v1/payroll/runs/", {"period_year": 2026, "period_month": 2})
        res2 = self.client.post("/api/v1/payroll/runs/", {"period_year": 2026, "period_month": 2})
        self.assertIn(res2.status_code, [400, 409])

    def test_list_payroll_runs(self):
        self.client.post("/api/v1/payroll/runs/", {"period_year": 2026, "period_month": 3})
        res = self.client.get("/api/v1/payroll/runs/")
        self.assertEqual(res.status_code, 200)
        data = res.data.get("results") or res.data
        self.assertGreater(len(data), 0)

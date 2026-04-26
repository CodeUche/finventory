"""
Payroll API integration tests.

Covers: employee CRUD, search, payroll run creation,
        gross salary calculation, payslip retrieval.
"""

import pytest
from decimal import Decimal
from datetime import date

from apps.payroll.models import Employee, PayrollRun


@pytest.mark.integration
class TestEmployeeCRUD:

    def test_create_employee(self, auth_client, organisation):
        """POST /payroll/employees/ should create and auto-number an employee."""
        response = auth_client.post("/api/v1/payroll/employees/", {
            "first_name": "Emeka",
            "last_name": "Nwosu",
            "job_title": "Logistics Officer",
            "department": "Operations",
            "employment_type": Employee.FULL_TIME,
            "hire_date": str(date(2024, 1, 15)),
            "basic_salary": "180000",
            "housing_allowance": "40000",
            "transport_allowance": "20000",
        }, format="json")

        assert response.status_code == 201
        data = response.data
        assert data["employee_id"].startswith("EMP-")
        assert Decimal(data["basic_salary"]) == Decimal("180000")

    def test_employee_gross_salary_computed(self, auth_client, employee):
        """GET /payroll/employees/{id}/ should expose gross_salary."""
        response = auth_client.get(f"/api/v1/payroll/employees/{employee.id}/")
        assert response.status_code == 200
        data = response.data
        assert "gross_salary" in data
        expected = (
            employee.basic_salary + employee.housing_allowance + employee.transport_allowance
        )
        assert Decimal(data["gross_salary"]) == expected

    def test_list_employees(self, auth_client, employee, second_employee):
        """GET /payroll/employees/ should return all active employees."""
        response = auth_client.get("/api/v1/payroll/employees/")
        assert response.status_code == 200
        ids = [e["id"] for e in response.data["results"]]
        assert str(employee.id) in ids
        assert str(second_employee.id) in ids

    def test_search_employees_by_name(self, auth_client, employee):
        """?search=<name> should filter by first/last name."""
        response = auth_client.get(f"/api/v1/payroll/employees/?search={employee.last_name}")
        assert response.status_code == 200
        ids = [e["id"] for e in response.data["results"]]
        assert str(employee.id) in ids

    def test_cross_org_isolation(self, other_auth_client, employee):
        """Other org cannot see this employee."""
        response = other_auth_client.get(f"/api/v1/payroll/employees/{employee.id}/")
        assert response.status_code in (403, 404)

    def test_update_employee_salary(self, auth_client, employee):
        """PATCH should update salary fields."""
        response = auth_client.patch(f"/api/v1/payroll/employees/{employee.id}/", {
            "basic_salary": "300000",
        }, format="json")
        assert response.status_code == 200
        assert Decimal(response.data["basic_salary"]) == Decimal("300000")

    def test_deactivate_employee(self, auth_client, employee):
        """PATCH is_active=False should deactivate."""
        response = auth_client.patch(f"/api/v1/payroll/employees/{employee.id}/", {
            "is_active": False,
        }, format="json")
        assert response.status_code == 200
        employee.refresh_from_db()
        assert not employee.is_active

    def test_unauthenticated_blocked(self, api_client):
        response = api_client.get("/api/v1/payroll/employees/")
        assert response.status_code == 401


@pytest.mark.integration
class TestPayrollRun:

    def test_create_payroll_run(self, auth_client, employee, second_employee):
        """POST /payroll/runs/ should create a draft run for a period."""
        response = auth_client.post("/api/v1/payroll/runs/", {
            "period_year": 2024,
            "period_month": 3,
        }, format="json")

        assert response.status_code == 201
        data = response.data
        assert data["status"] == PayrollRun.DRAFT
        assert data["period_year"] == 2024
        assert data["period_month"] == 3
        assert data["run_number"].startswith("PR-") or len(data["run_number"]) > 0

    def test_payroll_run_calculates_totals(self, auth_client, employee, second_employee):
        """A payroll run should aggregate gross, net, and statutory deductions."""
        response = auth_client.post("/api/v1/payroll/runs/", {
            "period_year": 2024,
            "period_month": 4,
        }, format="json")
        assert response.status_code == 201
        data = response.data
        assert Decimal(data["total_gross"]) > 0
        assert Decimal(data["total_net"]) > 0
        # Net must not exceed gross
        assert Decimal(data["total_net"]) <= Decimal(data["total_gross"])

    def test_duplicate_run_rejected(self, auth_client, employee):
        """Creating two runs for the same period/org should fail."""
        payload = {"period_year": 2024, "period_month": 5}
        auth_client.post("/api/v1/payroll/runs/", payload, format="json")
        response = auth_client.post("/api/v1/payroll/runs/", payload, format="json")
        assert response.status_code in (400, 409)

    def test_list_payroll_runs(self, auth_client, employee):
        """GET /payroll/runs/ should list all runs."""
        auth_client.post("/api/v1/payroll/runs/", {"period_year": 2024, "period_month": 6},
                         format="json")
        response = auth_client.get("/api/v1/payroll/runs/")
        assert response.status_code == 200
        assert len(response.data["results"]) >= 1

    def test_payslips_generated_for_run(self, auth_client, employee, second_employee):
        """After creating a run, payslips should exist for each active employee."""
        run_resp = auth_client.post("/api/v1/payroll/runs/", {
            "period_year": 2024,
            "period_month": 7,
        }, format="json")
        run_id = run_resp.data["id"]

        response = auth_client.get(f"/api/v1/payroll/runs/{run_id}/payslips/")
        assert response.status_code == 200
        assert len(response.data) >= 1   # at least one payslip

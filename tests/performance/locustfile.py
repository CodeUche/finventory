"""
Audity Performance / Load Tests — Locust

Test types covered:
  Load Testing     — expected concurrent users (10-50)
  Stress Testing   — ramp to 2× normal load
  Spike Testing    — sudden burst of 100 users
  Soak Testing     — sustained load over time (use --run-time 1h)

Usage:
  # Quick CI run (30 s, 10 users):
  locust -f locustfile.py --headless --users=10 --spawn-rate=2 \
         --run-time=30s --host=http://localhost:8000

  # Load test (5 min, 50 users):
  locust -f locustfile.py --headless --users=50 --spawn-rate=5 \
         --run-time=5m --host=http://localhost:8000

  # Interactive web UI:
  locust -f locustfile.py --host=http://localhost:8000

Environment variables:
  LOCUST_TEST_EMAIL    — test user email (default: testuser@audity.test)
  LOCUST_TEST_PASSWORD — test user password (default: StrongPass123!)
  LOCUST_ORG_ID        — UUID of the test organisation
"""

import os
import json
import random
from locust import HttpUser, task, between, events
from locust.runners import MasterRunner


# ─── Config ───────────────────────────────────────────────────────────────────

TEST_EMAIL    = os.getenv("LOCUST_TEST_EMAIL",    "testuser@audity.test")
TEST_PASSWORD = os.getenv("LOCUST_TEST_PASSWORD", "StrongPass123!")
TEST_ORG_ID   = os.getenv("LOCUST_ORG_ID",        "")   # populated after login

PRODUCT_IDS:  list[str] = []
CUSTOMER_IDS: list[str] = []
WAREHOUSE_ID: str = ""


# ─── Bootstrap (runs once before the test starts) ─────────────────────────────

@events.test_start.add_listener
def seed_ids(environment, **kwargs):
    """
    Fetch a token, then pre-load product / customer / warehouse IDs so that
    individual tasks can pick from real UUIDs without extra auth overhead.
    Only runs on the master (or single) node.
    """
    if isinstance(environment.runner, MasterRunner):
        return   # workers will seed themselves

    host = environment.host or "http://localhost:8000"
    import requests

    resp = requests.post(f"{host}/api/v1/auth/login/", json={
        "email": TEST_EMAIL, "password": TEST_PASSWORD
    }, timeout=10)
    if resp.status_code != 200:
        print(f"[locust] WARNING: seed login failed ({resp.status_code}) — tasks may 401")
        return

    token = resp.json().get("access", "")
    headers = {"Authorization": f"Bearer {token}"}

    # Resolve organisation
    orgs_resp = requests.get(f"{host}/api/v1/tenancy/organisations/",
                             headers=headers, timeout=10)
    if orgs_resp.ok and orgs_resp.json().get("results"):
        global TEST_ORG_ID
        TEST_ORG_ID = orgs_resp.json()["results"][0]["id"]
        headers["X-Organisation-ID"] = TEST_ORG_ID

    # Products
    prods_resp = requests.get(f"{host}/api/v1/inventory/products/?page_size=50",
                              headers=headers, timeout=10)
    if prods_resp.ok:
        PRODUCT_IDS.extend(
            [p["id"] for p in prods_resp.json().get("results", [])]
        )

    # Customers
    custs_resp = requests.get(f"{host}/api/v1/customers/?page_size=50",
                              headers=headers, timeout=10)
    if custs_resp.ok:
        CUSTOMER_IDS.extend(
            [c["id"] for c in custs_resp.json().get("results", [])]
        )

    # Default warehouse
    wh_resp = requests.get(f"{host}/api/v1/inventory/warehouses/",
                           headers=headers, timeout=10)
    if wh_resp.ok and wh_resp.json().get("results"):
        global WAREHOUSE_ID
        WAREHOUSE_ID = wh_resp.json()["results"][0]["id"]

    print(f"[locust] seeded: {len(PRODUCT_IDS)} products, "
          f"{len(CUSTOMER_IDS)} customers, warehouse={WAREHOUSE_ID}")


# ─── Base user ────────────────────────────────────────────────────────────────

class AudityUser(HttpUser):
    """
    Simulates a typical business user: logs in once, then cycles through
    a realistic mix of read-heavy and write operations.
    """
    abstract = True
    wait_time = between(0.5, 2.0)

    token: str = ""
    org_id: str = ""

    def on_start(self):
        """Authenticate and store the JWT token."""
        resp = self.client.post("/api/v1/auth/login/", json={
            "email": TEST_EMAIL,
            "password": TEST_PASSWORD,
        }, name="/auth/login")

        if resp.status_code == 200:
            self.token = resp.json().get("access", "")
            # Use seeded org or discover it
            if TEST_ORG_ID:
                self.org_id = TEST_ORG_ID
            else:
                orgs = self.client.get(
                    "/api/v1/tenancy/organisations/",
                    headers=self._headers(),
                    name="/tenancy/organisations",
                )
                if orgs.ok and orgs.json().get("results"):
                    self.org_id = orgs.json()["results"][0]["id"]

    def _headers(self) -> dict:
        h = {"Authorization": f"Bearer {self.token}"}
        if self.org_id:
            h["X-Organisation-ID"] = self.org_id
        return h


# ─── Read-heavy user (70 % of traffic) ───────────────────────────────────────

class ReadUser(AudityUser):
    weight = 70

    @task(5)
    def view_dashboard(self):
        self.client.get("/api/v1/reports/dashboard/",
                        headers=self._headers(), name="/reports/dashboard")

    @task(4)
    def list_invoices(self):
        self.client.get("/api/v1/sales/invoices/",
                        headers=self._headers(), name="/sales/invoices [list]")

    @task(3)
    def list_products(self):
        self.client.get("/api/v1/inventory/products/",
                        headers=self._headers(), name="/inventory/products [list]")

    @task(3)
    def list_customers(self):
        self.client.get("/api/v1/customers/",
                        headers=self._headers(), name="/customers [list]")

    @task(2)
    def list_bills(self):
        self.client.get("/api/v1/bills/",
                        headers=self._headers(), name="/bills [list]")

    @task(2)
    def profit_and_loss(self):
        self.client.get("/api/v1/reports/profit-loss/",
                        headers=self._headers(), name="/reports/profit-loss")

    @task(2)
    def balance_sheet(self):
        self.client.get("/api/v1/reports/balance-sheet/",
                        headers=self._headers(), name="/reports/balance-sheet")

    @task(2)
    def list_expenses(self):
        self.client.get("/api/v1/expenses/",
                        headers=self._headers(), name="/expenses [list]")

    @task(1)
    def list_employees(self):
        self.client.get("/api/v1/payroll/employees/",
                        headers=self._headers(), name="/payroll/employees [list]")

    @task(1)
    def list_quotes(self):
        self.client.get("/api/v1/sales/quotes/",
                        headers=self._headers(), name="/sales/quotes [list]")

    @task(1)
    def search_products(self):
        query = random.choice(["Johnnie", "Hennessy", "Walker", "Gold", "Black"])
        self.client.get(f"/api/v1/inventory/products/?search={query}",
                        headers=self._headers(), name="/inventory/products [search]")

    @task(1)
    def view_single_product(self):
        if PRODUCT_IDS:
            pid = random.choice(PRODUCT_IDS)
            self.client.get(f"/api/v1/inventory/products/{pid}/",
                            headers=self._headers(), name="/inventory/products [detail]")

    @task(1)
    def view_single_customer(self):
        if CUSTOMER_IDS:
            cid = random.choice(CUSTOMER_IDS)
            self.client.get(f"/api/v1/customers/{cid}/",
                            headers=self._headers(), name="/customers [detail]")


# ─── Write user (30 % of traffic) ────────────────────────────────────────────

class WriteUser(AudityUser):
    weight = 30

    @task(3)
    def create_expense(self):
        self.client.post("/api/v1/expenses/", json={
            "amount": str(round(random.uniform(1000, 50000), 2)),
            "description": f"Load-test expense {random.randint(1000, 9999)}",
            "category_label": random.choice([
                "Office Supplies", "Transport", "Utilities", "Marketing"
            ]),
            "date": "2024-06-01",
        }, headers=self._headers(), name="/expenses [create]")

    @task(2)
    def create_customer(self):
        n = random.randint(10000, 99999)
        self.client.post("/api/v1/customers/", json={
            "code": f"PERF-{n}",
            "name": f"Perf Test Customer {n}",
        }, headers=self._headers(), name="/customers [create]")

    @task(2)
    def create_quote(self):
        if not PRODUCT_IDS or not WAREHOUSE_ID:
            return
        self.client.post("/api/v1/sales/quotes/", json={
            "warehouse_id": WAREHOUSE_ID,
            "issue_date": "2024-06-01",
            "valid_until": "2024-06-15",
            "items": [{
                "product_id": random.choice(PRODUCT_IDS),
                "quantity": str(random.randint(1, 5)),
                "unit_price": str(round(random.uniform(5000, 20000), 2)),
            }],
        }, headers=self._headers(), name="/sales/quotes [create]")

    @task(1)
    def token_refresh(self):
        """Simulate the periodic token refresh the frontend does."""
        self.client.post("/api/v1/auth/token/refresh/",
                         json={"refresh": ""},     # will 401 — measures endpoint latency
                         name="/auth/token/refresh",
                         catch_response=True)

    @task(1)
    def profile_fetch(self):
        self.client.get("/api/v1/auth/profile/",
                        headers=self._headers(), name="/auth/profile")


# ─── Spike user (simulates a sudden burst) ────────────────────────────────────

class SpikeUser(AudityUser):
    """
    High-velocity read-only user for spike testing.
    Spawn 100 of these simultaneously to simulate a traffic burst.
    """
    weight = 0   # not included in normal runs; instantiate with --class-picker
    wait_time = between(0.1, 0.5)

    @task
    def hit_dashboard(self):
        self.client.get("/api/v1/reports/dashboard/",
                        headers=self._headers(), name="/reports/dashboard [spike]")

"""
Global test fixtures for Audity (Finventory).

Fixtures use factory_boy for clean, composable test data.
All tests run against the testing settings (SQLite in-memory, no caching).

Organisation: root-level conftest  →  run from backend/ directory
  cd finventory/backend && pytest apps/ ../tests/ -v
"""

import pytest
from decimal import Decimal
from datetime import date, timedelta


# ─── Users ────────────────────────────────────────────────────────────────────

@pytest.fixture
def user(db):
    """A basic verified user (will become org owner)."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return User.objects.create_user(
        email="testuser@audity.test",
        password="StrongPass123!",
        first_name="Test",
        last_name="User",
        is_verified=True,
    )


@pytest.fixture
def admin_user(db):
    """A second verified user (used for cross-org / permission tests)."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return User.objects.create_user(
        email="admin@audity.test",
        password="AdminPass123!",
        first_name="Admin",
        last_name="User",
        is_verified=True,
    )


@pytest.fixture
def superuser(db):
    """A Django superuser (platform admin)."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return User.objects.create_superuser(
        email="super@audity.test",
        password="SuperPass123!",
        first_name="Super",
        last_name="Admin",
        is_verified=True,
    )


@pytest.fixture
def other_user(db):
    """A third user belonging to a *different* organisation (isolation tests)."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return User.objects.create_user(
        email="other@audity.test",
        password="OtherPass123!",
        first_name="Other",
        last_name="User",
        is_verified=True,
    )


# ─── Organisations & Memberships ──────────────────────────────────────────────

@pytest.fixture
def organisation(db, user):
    """A test organisation with the user as OWNER and unrestricted plan access."""
    from apps.tenancy.services import OrganisationService
    org = OrganisationService.create_organisation(
        name="Test Liquor Distributors Ltd",
        owner=user,
        extra={"country": "NG", "currency": "NGN"},
    )
    # Ensure the subscription plan allows all modules so plan_requires() gates
    # never block tests — test suites verify feature logic, not plan gating.
    sub = getattr(org, "subscription", None)
    if sub and sub.plan:
        from apps.subscriptions.models import Plan
        sub.plan.features.pop("modules", None)
        Plan.objects.filter(pk=sub.plan.pk).update(features=sub.plan.features)
    return org


@pytest.fixture
def other_organisation(db, other_user):
    """A second organisation owned by other_user (for isolation tests)."""
    from apps.tenancy.services import OrganisationService
    org = OrganisationService.create_organisation(
        name="Other Business Ltd",
        owner=other_user,
        extra={"country": "NG", "currency": "NGN"},
    )
    sub = getattr(org, "subscription", None)
    if sub and sub.plan:
        from apps.subscriptions.models import Plan
        sub.plan.features.pop("modules", None)
        Plan.objects.filter(pk=sub.plan.pk).update(features=sub.plan.features)
    return org


@pytest.fixture
def membership(db, organisation, user):
    """The owner's membership in the test org."""
    from apps.tenancy.models import Membership
    return Membership.objects.get(user=user, organisation=organisation)


# ─── API clients ──────────────────────────────────────────────────────────────

@pytest.fixture
def api_client():
    from rest_framework.test import APIClient
    return APIClient()


@pytest.fixture
def auth_client(api_client, user, organisation):
    """API client authenticated as the owner with org header set."""
    from rest_framework_simplejwt.tokens import RefreshToken
    refresh = RefreshToken.for_user(user)
    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}",
        HTTP_X_ORGANISATION_ID=str(organisation.id),
    )
    return api_client


@pytest.fixture
def other_auth_client(api_client, other_user, other_organisation):
    """API client for other_user / other_organisation."""
    from rest_framework_simplejwt.tokens import RefreshToken
    from rest_framework.test import APIClient
    client = APIClient()
    refresh = RefreshToken.for_user(other_user)
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}",
        HTTP_X_ORGANISATION_ID=str(other_organisation.id),
    )
    return client


@pytest.fixture
def superuser_client(api_client, superuser, organisation):
    """Superuser client (platform-admin tests)."""
    from rest_framework_simplejwt.tokens import RefreshToken
    from rest_framework.test import APIClient
    client = APIClient()
    refresh = RefreshToken.for_user(superuser)
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}",
        HTTP_X_ORGANISATION_ID=str(organisation.id),
    )
    return client


# ─── Inventory ────────────────────────────────────────────────────────────────

@pytest.fixture
def warehouse(db, organisation, user):
    from apps.inventory.models import Warehouse
    return Warehouse.objects.create(
        organisation=organisation,
        name="Main Warehouse",
        is_default=True,
    )


@pytest.fixture
def tax_class(db, organisation):
    from apps.tax.models import TaxClass
    return TaxClass.objects.create(
        organisation=organisation,
        name="Standard VAT",
        rate=Decimal("7.5"),
    )


@pytest.fixture
def product(db, organisation, warehouse, tax_class):
    from apps.inventory.models import Product
    return Product.objects.create(
        organisation=organisation,
        sku="LQR-001",
        name="Johnnie Walker Black 750ml",
        brand="Johnnie Walker",
        cost_price=Decimal("5500.00"),
        selling_price=Decimal("8500.00"),
        is_taxable=True,
        tax_class=tax_class,
        reorder_level=10,
    )


@pytest.fixture
def service_product(db, organisation, tax_class):
    """A service-type product (no stock movements)."""
    from apps.inventory.models import Product
    return Product.objects.create(
        organisation=organisation,
        sku="SVC-001",
        name="Delivery Service",
        product_type="service",
        cost_price=Decimal("0.00"),
        selling_price=Decimal("2000.00"),
        is_taxable=False,
    )


@pytest.fixture
def stocked_product(db, product, organisation, warehouse, user):
    """Product with 100 units in stock via an opening movement."""
    from apps.inventory.services import InventoryService
    InventoryService.record_movement(
        organisation=organisation,
        product=product,
        warehouse=warehouse,
        quantity=Decimal("100"),
        movement_type="opening",
        unit_cost=product.cost_price,
        reference="OPENING",
        created_by=user,
    )
    product.refresh_from_db()
    return product


# ─── Customers ────────────────────────────────────────────────────────────────

@pytest.fixture
def customer(db, organisation):
    from apps.customers.models import Customer
    return Customer.objects.create(
        organisation=organisation,
        code="CUST-001",
        name="Lagos Wine Merchants",
        email="lvm@example.com",
        phone="08012345678",
        credit_limit=Decimal("500000"),
        payment_terms_days=30,
    )


@pytest.fixture
def second_customer(db, organisation):
    from apps.customers.models import Customer
    return Customer.objects.create(
        organisation=organisation,
        code="CUST-002",
        name="Abuja Beverages Ltd",
        credit_limit=Decimal("200000"),
        payment_terms_days=15,
    )


# ─── Suppliers ────────────────────────────────────────────────────────────────

@pytest.fixture
def supplier(db, organisation):
    from apps.suppliers.models import Supplier
    return Supplier.objects.create(
        organisation=organisation,
        code="SUP-001",
        name="Diageo Nigeria Ltd",
        email="diageo@example.com",
        phone="09087654321",
        payment_terms_days=30,
    )


# ─── Subscriptions / Plans ────────────────────────────────────────────────────

@pytest.fixture
def plan(db):
    from apps.subscriptions.models import Plan
    return Plan.objects.create(
        name="Pro",
        slug="pro",
        price=Decimal("29999"),
        interval=Plan.Interval.MONTHLY,
        features={
            "max_products": 1000,
            "max_users": 10,
            "multi_warehouse": True,
            "advanced_reports": True,
            "api_access": True,
        },
    )


# ─── Tax ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def nigeria_pit_config(db, organisation):
    """Nigeria Personal Income Tax config with full bracket table."""
    from apps.tax.models import TaxBracket, TaxConfig
    config = TaxConfig.objects.create(
        organisation=organisation,
        name="Nigeria PIT 2024",
        tax_type=TaxConfig.TaxType.INCOME,
        country="NG",
        tax_year=2024,
        is_progressive=True,
        personal_allowance=Decimal("200000"),
    )
    brackets = [
        (0,       300000,  Decimal("7")),
        (300000,  600000,  Decimal("11")),
        (600000,  1100000, Decimal("15")),
        (1100000, 1600000, Decimal("19")),
        (1600000, 3200000, Decimal("21")),
        (3200000, None,    Decimal("24")),
    ]
    for lower, upper, rate in brackets:
        TaxBracket.objects.create(
            config=config, lower_bound=lower, upper_bound=upper, rate=rate
        )
    return config


# ─── Employees ────────────────────────────────────────────────────────────────

@pytest.fixture
def employee(db, organisation):
    from apps.payroll.models import Employee
    return Employee.objects.create(
        organisation=organisation,
        first_name="Chidi",
        last_name="Okeke",
        email="chidi@audity.test",
        job_title="Sales Manager",
        department="Sales",
        employment_type=Employee.FULL_TIME,
        hire_date=date(2023, 1, 15),
        basic_salary=Decimal("250000"),
        housing_allowance=Decimal("50000"),
        transport_allowance=Decimal("30000"),
    )


@pytest.fixture
def second_employee(db, organisation):
    from apps.payroll.models import Employee
    return Employee.objects.create(
        organisation=organisation,
        first_name="Amaka",
        last_name="Eze",
        email="amaka@audity.test",
        job_title="Accountant",
        department="Finance",
        employment_type=Employee.FULL_TIME,
        hire_date=date(2023, 3, 1),
        basic_salary=Decimal("180000"),
        housing_allowance=Decimal("40000"),
        transport_allowance=Decimal("20000"),
    )


# ─── Bills ────────────────────────────────────────────────────────────────────

@pytest.fixture
def bill(db, organisation, supplier, user):
    """A draft bill with one line item."""
    from apps.bills.models import Bill, BillItem
    b = Bill.objects.create(
        organisation=organisation,
        supplier=supplier,
        status=Bill.DRAFT,
        issue_date=date.today(),
        due_date=date.today() + timedelta(days=30),
        subtotal=Decimal("50000"),
        tax_amount=Decimal("3750"),
        total_amount=Decimal("53750"),
        amount_due=Decimal("53750"),
        created_by=user,
    )
    BillItem.objects.create(
        organisation=organisation,
        bill=b,
        description="Johnnie Walker Black Label × 10 cases",
        quantity=Decimal("10"),
        unit_cost=Decimal("5000"),
        line_total=Decimal("50000"),
    )
    return b


# ─── Quotes ───────────────────────────────────────────────────────────────────

@pytest.fixture
def quote(db, organisation, customer, warehouse, stocked_product, user):
    """A draft quote with one line item."""
    from apps.quotes.models import Quote, QuoteItem
    q = Quote.objects.create(
        organisation=organisation,
        customer=customer,
        warehouse=warehouse,
        status=Quote.DRAFT,
        issue_date=date.today(),
        valid_until=date.today() + timedelta(days=14),
        subtotal=Decimal("17000"),
        total_amount=Decimal("17000"),
        created_by=user,
    )
    QuoteItem.objects.create(
        organisation=organisation,
        quote=q,
        product=stocked_product,
        quantity=Decimal("2"),
        unit_price=stocked_product.selling_price,
        line_total=Decimal("17000"),
    )
    return q


# ─── Budgets ──────────────────────────────────────────────────────────────────

@pytest.fixture
def expense_category(db, organisation):
    from apps.expenses.models import ExpenseCategory
    return ExpenseCategory.objects.create(
        organisation=organisation,
        name="Office Supplies",
    )

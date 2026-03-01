"""
Global test fixtures for Finventory.

Fixtures use factory_boy for clean, composable test data.
All tests run against the testing settings (SQLite, no caching).
"""

import pytest
from decimal import Decimal
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture
def user(db):
    """A basic authenticated user."""
    return User.objects.create_user(
        email="testuser@finventory.test",
        password="StrongPass123!",
        first_name="Test",
        last_name="User",
        is_verified=True,
    )


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        email="admin@finventory.test",
        password="AdminPass123!",
        first_name="Admin",
        last_name="User",
        is_verified=True,
    )


@pytest.fixture
def organisation(db, user):
    """A test organisation with the user as OWNER."""
    from apps.tenancy.services import OrganisationService
    return OrganisationService.create_organisation(
        name="Test Liquor Distributors Ltd",
        owner=user,
        extra={"country": "NG", "currency": "NGN"},
    )


@pytest.fixture
def membership(db, organisation, user):
    """The user's membership in the test org."""
    from apps.tenancy.models import Membership
    return Membership.objects.get(user=user, organisation=organisation)


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient
    return APIClient()


@pytest.fixture
def auth_client(api_client, user, organisation):
    """API client authenticated as the test user with org header."""
    from rest_framework_simplejwt.tokens import RefreshToken
    refresh = RefreshToken.for_user(user)
    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}",
        HTTP_X_ORGANISATION_ID=str(organisation.id),
    )
    return api_client


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
def stocked_product(db, product, organisation, warehouse, user):
    """Product with 100 units in stock."""
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


@pytest.fixture
def customer(db, organisation):
    from apps.customers.models import Customer
    return Customer.objects.create(
        organisation=organisation,
        code="CUST-001",
        name="Lagos Wine Merchants",
        credit_limit=Decimal("500000"),
        payment_terms_days=30,
    )


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


@pytest.fixture
def nigeria_pit_config(db, organisation):
    """Nigeria Personal Income Tax configuration with brackets."""
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
        (0, 300000, Decimal("7")),
        (300000, 600000, Decimal("11")),
        (600000, 1100000, Decimal("15")),
        (1100000, 1600000, Decimal("19")),
        (1600000, 3200000, Decimal("21")),
        (3200000, None, Decimal("24")),
    ]
    for lower, upper, rate in brackets:
        TaxBracket.objects.create(config=config, lower_bound=lower, upper_bound=upper, rate=rate)
    return config

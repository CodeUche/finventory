"""
Load a believable demo company into the staging environment.

WHY THIS EXISTS
    An empty environment proves nothing. Half the bugs worth catching before a
    release only appear once there are rows to list, sort, page, total and post
    to a ledger. An empty products table never reproduced the N+1 that made the
    page take 6.7 seconds. So staging needs data, and it needs the same data
    every time, or a test result is not comparable with the last one.

WHAT IT CREATES
    One organisation, a full chart of accounts, four users at four different
    roles, a default warehouse, product categories, products with opening stock,
    customers and suppliers.

WHAT IT DELIBERATELY DOES NOT CREATE
    Invoices, bills, payments and journals. Those are what you are testing: they
    should be created through the UI or the API so the posting logic, the GL
    mapping and the permission checks all actually run. Seeding them directly
    would write rows the real code path never produced, and a green screen built
    on those is worth nothing.

SAFETY
    Refuses to run unless settings.IS_STAGING is True. Only
    config.settings.staging sets that, so this command cannot be pointed at
    production or at a hosted database by accident. Every address is on a .test
    domain, which RFC 2606 reserves and nothing routes, so no mail can reach a
    seeded account even if email were switched on.

USAGE
    ./scripts/staging.sh seed
    ./scripts/staging.sh manage seed_staging --wipe    # start the demo org over
"""
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

ORG_SLUG = "audity-staging-demo"
ORG_NAME = "Staging Demo Trading Ltd"
DEFAULT_PASSWORD = "StagingPass123!"

# (email, first, last, role)
USERS = [
    ("staging.owner@audity.test",      "Ada",    "Owner",      "owner"),
    ("staging.manager@audity.test",    "Bode",   "Manager",    "manager"),
    ("staging.accountant@audity.test", "Chidi",  "Accountant", "accountant"),
    ("staging.staff@audity.test",      "Deborah", "Staff",     "staff"),
]

CATEGORIES = ["Beverages", "Dry Goods", "Household", "Stationery", "Services"]

# (sku, name, category, cost, price, opening_qty, reorder_level)
PRODUCTS = [
    ("BEV-001", "Bottled Water 75cl (pack of 12)", "Beverages",  1800,  2500, 120, 20),
    ("BEV-002", "Malt Drink 33cl (crate of 24)",   "Beverages",  7200,  9000,  45, 10),
    ("BEV-003", "Orange Juice 1L",                 "Beverages",   950,  1400,  80, 15),
    ("BEV-004", "Instant Coffee 200g",             "Beverages",  3100,  4200,  18, 20),
    ("DRY-001", "Long Grain Rice 5kg",             "Dry Goods",  6800,  8500,  60, 12),
    ("DRY-002", "Vegetable Oil 3L",                "Dry Goods",  5400,  6900,  35, 10),
    ("DRY-003", "Granulated Sugar 1kg",            "Dry Goods",  1100,  1600,   8, 25),
    ("DRY-004", "Table Salt 500g",                 "Dry Goods",   350,   600, 200, 30),
    ("HH-001",  "Liquid Detergent 2L",             "Household",  2700,  3800,  52, 15),
    ("HH-002",  "Bar Soap (pack of 4)",            "Household",  1450,  2100,  90, 20),
    ("HH-003",  "Bleach 1L",                       "Household",   980,  1500,   0, 10),
    ("STA-001", "A4 Paper Ream",                   "Stationery", 4200,  5600,  24,  8),
    ("STA-002", "Ballpoint Pens (box of 50)",      "Stationery", 2300,  3400,  16, 10),
    ("SVC-001", "Delivery Within Lagos",           "Services",      0,  3500,   0,  0),
]

# (code, name, type, terms_days, credit_limit)
CUSTOMERS = [
    ("CUST-001", "Lekki Provisions Store",     "retail",      0,        0),
    ("CUST-002", "Ikeja Wholesale Depot",      "wholesale",  30,  2500000),
    ("CUST-003", "Victoria Island Hotels Ltd", "corporate",  45,  5000000),
    ("CUST-004", "Yaba Mini Mart",             "retail",     14,   400000),
    ("CUST-005", "Surulere Distributors",      "distributor", 30, 3000000),
    ("CUST-006", "Federal Ministry Canteen",   "government", 60,  1500000),
    ("CUST-007", "Walk-in Customer",           "retail",      0,        0),
    ("CUST-008", "Ajah Community School",      "ngo",        30,   750000),
]

# (code, name, terms_days)
SUPPLIERS = [
    ("SUP-001", "Apapa Bulk Importers Ltd",   30),
    ("SUP-002", "Ogun State Beverage Plant",  14),
    ("SUP-003", "Alaba Packaging Supplies",    7),
    ("SUP-004", "Mainland Logistics Partners", 30),
    ("SUP-005", "Lagos Stationery Wholesale",  21),
]


class Command(BaseCommand):
    help = "Seed the staging environment with a demo organisation and master data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--wipe", action="store_true",
            help="Delete the demo organisation first, so the seed starts from nothing.",
        )
        parser.add_argument(
            "--password", default=None,
            help="Password for the seeded users (default: $STAGING_SEED_PASSWORD).",
        )

    def handle(self, *args, **opts):
        # The one check that makes everything below safe to run.
        if not getattr(settings, "IS_STAGING", False):
            raise CommandError(
                "seed_staging refuses to run outside the staging environment. "
                "Current settings module does not set IS_STAGING = True. Use "
                "DJANGO_SETTINGS_MODULE=config.settings.staging, or run it "
                "through ./scripts/staging.sh."
            )

        from decouple import config as env
        password = opts["password"] or env("STAGING_SEED_PASSWORD", default=DEFAULT_PASSWORD)

        if opts["wipe"]:
            self._wipe()

        with transaction.atomic():
            org, owner = self._organisation(password)
            self._chart_of_accounts(org)
            members = self._users(org, owner, password)
            warehouse = self._warehouse(org)
            categories = self._categories(org)
            self._products(org, warehouse, categories, members["owner"])
            self._customers(org)
            self._suppliers(org)

        self._report(org, password)

    # ── steps ────────────────────────────────────────────────────────────────
    def _wipe(self):
        from apps.tenancy.models import Organisation

        # all_objects, not objects: the default manager filters out soft-deleted
        # rows, so a previously wiped org would be invisible here and the
        # unique slug would then collide on re-seed.
        manager = getattr(Organisation, "all_objects", Organisation.objects)
        existing = manager.filter(slug=ORG_SLUG).first()
        if not existing:
            self.stdout.write("  nothing to wipe")
            return
        self.stdout.write(self.style.WARNING(f"  deleting existing org {existing.pk}"))
        # hard_delete where the model offers it, so the slug is genuinely free.
        if hasattr(existing, "hard_delete"):
            existing.hard_delete()
        else:
            super(type(existing), existing).delete()

    def _organisation(self, password):
        from django.contrib.auth import get_user_model
        from apps.tenancy.models import Organisation

        User = get_user_model()
        email, first, last, _ = USERS[0]
        owner, created = User.objects.get_or_create(
            email=email,
            defaults={
                "first_name": first, "last_name": last,
                "is_active": True, "is_verified": True,
            },
        )
        owner.set_password(password)
        owner.is_active = True
        owner.is_verified = True
        # Terms are accepted up front: the gate otherwise blocks every click in a
        # UI walkthrough before anything under test is reachable.
        if hasattr(owner, "terms_accepted_at") and not owner.terms_accepted_at:
            owner.terms_accepted_at = timezone.now()
            owner.terms_accepted_version = "staging-seed"
        owner.save()

        org, _ = Organisation.objects.get_or_create(
            slug=ORG_SLUG,
            defaults={
                "name": ORG_NAME,
                "owner": owner,
                "country": "NG",
                "currency": "NGN",
                "tax_id": "12345678-0001",
                "registration_number": "RC-STAGING-0001",
                "email": "accounts@staging-demo.test",
                "phone": "+2348000000000",
                "address": "14 Test Close, Ajah, Lagos",
                "onboarding_completed": True,
                "is_active": True,
            },
        )
        self.stdout.write(f"  organisation: {org.name} ({org.pk})")
        return org, owner

    def _chart_of_accounts(self, org):
        from apps.accounting.models import Account
        from apps.accounting.services import AccountingService

        # No post_save signal creates a COA, so seed it explicitly, with the same
        # call reseed_coa uses. get_or_create inside makes it safe to repeat.
        AccountingService.seed_chart_of_accounts(org)
        self.stdout.write(f"  chart of accounts: {Account.objects.filter(organisation=org).count()} accounts")

    def _users(self, org, owner, password):
        from django.contrib.auth import get_user_model
        from apps.tenancy.models import Membership

        User = get_user_model()
        members = {}
        for email, first, last, role in USERS:
            user = owner if email == owner.email else None
            if user is None:
                user, _ = User.objects.get_or_create(
                    email=email,
                    defaults={"first_name": first, "last_name": last},
                )
                user.set_password(password)
                user.is_active = True
                user.is_verified = True
                if hasattr(user, "terms_accepted_at") and not user.terms_accepted_at:
                    user.terms_accepted_at = timezone.now()
                    user.terms_accepted_version = "staging-seed"
                user.save()
            Membership.objects.get_or_create(
                user=user, organisation=org,
                defaults={"role": role, "is_active": True, "joined_at": timezone.now()},
            )
            members[role] = user
        self.stdout.write(f"  users: {', '.join(r for r in members)}")
        return members

    def _warehouse(self, org):
        from apps.inventory.models import Warehouse

        warehouse, _ = Warehouse.objects.get_or_create(
            organisation=org, name="Main Store",
            defaults={"is_default": True, "is_active": True,
                      "address": "14 Test Close, Ajah, Lagos"},
        )
        self.stdout.write(f"  warehouse: {warehouse.name}")
        return warehouse

    def _categories(self, org):
        from apps.inventory.models import Category

        out = {}
        for name in CATEGORIES:
            out[name], _ = Category.objects.get_or_create(organisation=org, name=name)
        self.stdout.write(f"  categories: {len(out)}")
        return out

    def _products(self, org, warehouse, categories, actor):
        from apps.inventory.models import Product
        from apps.inventory.services import InventoryService

        created = 0
        stocked = 0
        for sku, name, cat, cost, price, qty, reorder in PRODUCTS:
            product, made = Product.objects.get_or_create(
                organisation=org, sku=sku,
                defaults={
                    "name": name,
                    "category": categories.get(cat),
                    "cost_price": Decimal(cost),
                    "selling_price": Decimal(price),
                    "reorder_level": reorder,
                    "is_active": True,
                },
            )
            created += int(made)
            # A StockItem row only exists once a movement has been recorded, so
            # opening stock has to go through record_movement. Setting a
            # quantity field directly would leave the product at zero stock and
            # no ledger trail. Only on first creation, or a repeat seed would
            # keep adding stock.
            if made and qty:
                InventoryService.record_movement(
                    organisation=org,
                    product=product,
                    warehouse=warehouse,
                    quantity=Decimal(qty),
                    movement_type="opening",
                    unit_cost=Decimal(cost),
                    reference=f"STAGING-SEED-{sku}",
                    notes="Opening stock loaded by seed_staging",
                    created_by=actor,
                )
                stocked += 1
        # Bleach and the service line are seeded at zero on purpose: the
        # low-stock tile and the out-of-stock paths need something to show.
        self.stdout.write(f"  products: {created} new, {stocked} given opening stock")

    def _customers(self, org):
        from apps.customers.models import Customer

        n = 0
        for code, name, ctype, terms, limit in CUSTOMERS:
            _, made = Customer.objects.get_or_create(
                organisation=org, code=code,
                defaults={
                    "name": name, "customer_type": ctype,
                    "payment_terms_days": terms,
                    "credit_limit": Decimal(limit),
                    "email": f"{code.lower()}@staging-demo.test",
                    "phone": "+2348010000000",
                    "address": "Lagos, Nigeria",
                    "is_active": True,
                },
            )
            n += int(made)
        self.stdout.write(f"  customers: {n} new")

    def _suppliers(self, org):
        from apps.suppliers.models import Supplier

        n = 0
        for code, name, terms in SUPPLIERS:
            _, made = Supplier.objects.get_or_create(
                organisation=org, code=code,
                defaults={
                    "name": name, "payment_terms_days": terms,
                    "email": f"{code.lower()}@staging-demo.test",
                    "phone": "+2348020000000",
                    "address": "Lagos, Nigeria",
                    "is_active": True,
                },
            )
            n += int(made)
        self.stdout.write(f"  suppliers: {n} new")

    # ── output ───────────────────────────────────────────────────────────────
    def _report(self, org, password):
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Staging seeded."))
        self.stdout.write("")
        self.stdout.write(f"  Organisation   {org.name}")
        self.stdout.write(f"  Org ID         {org.pk}")
        self.stdout.write(f"  Password       {password}   (all four accounts)")
        self.stdout.write("")
        for email, _, _, role in USERS:
            self.stdout.write(f"  {role:<11}{email}")
        self.stdout.write("")
        self.stdout.write("  Sign in at http://localhost:5174 with the staging frontend running")
        self.stdout.write("  (cd frontend && npm run dev:staging)")
        self.stdout.write("")
        self.stdout.write("  Invoices, bills and journals are intentionally not seeded. Create")
        self.stdout.write("  them through the UI so the posting logic is what actually runs.")
        self.stdout.write("")

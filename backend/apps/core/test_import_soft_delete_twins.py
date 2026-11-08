"""
Re-importing a name that exists twice: once live, once soft-deleted.

The unique constraints on Warehouse (organisation, name) and Product
(organisation, sku) only cover live rows (condition is_deleted=False), so an
organisation can legitimately hold a live record AND a deleted record with the
same name. The importers fall back to soft-deleted rows so a deleted record is
revived instead of duplicated, but the LIVE row must always win. If a deleted
twin is picked while a live one exists, reviving it puts two live rows on one
name and breaks the constraint.

Each test uses several twins in one file, because a lookup with no ordering
returns an arbitrary one of the two and a single pair would pass half the time
by luck.
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounting.tests import _upgrade_to_business
from apps.authentication.models import User
from apps.inventory.models import Product, Warehouse
from apps.purchases.models import PurchaseOrder
from apps.suppliers.models import Supplier
from apps.tenancy.services import OrganisationService

TWINS = 8


def _setup(test, tag):
    user = User.objects.create_user(
        email=f"twin_{tag}@example.com", password="TestPass123!",
        first_name="Twin", last_name=tag, is_verified=True,
    )
    test.org = OrganisationService.create_organisation(
        name=f"Twins {tag}", owner=user, extra={"currency": "NGN", "country": "NG"},
    )
    _upgrade_to_business(test.org)
    test.client = APIClient()
    test.client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {str(RefreshToken.for_user(user).access_token)}",
        HTTP_X_ORGANISATION_ID=str(test.org.id),
    )


def _post(client, entity, text):
    up = SimpleUploadedFile(f"{entity}.csv", text.encode("utf-8"), content_type="text/csv")
    return client.post(f"/api/v1/import/{entity}/", {"file": up}, format="multipart")


def _make_twin(model, org, **ident):
    """Create a soft-deleted record, then a live one with the same identity."""
    deleted = model.all_objects.create(
        organisation=org, is_deleted=True, deleted_at=timezone.now(), **ident,
    )
    live = model.objects.create(organisation=org, **ident)
    return deleted, live


class WarehouseTwinTests(TestCase):

    def setUp(self):
        _setup(self, "wh")

    def test_products_import_uses_the_live_warehouse_not_the_deleted_twin(self):
        pairs = {}
        for i in range(TWINS):
            name = f"WH-{i}"
            pairs[name] = _make_twin(Warehouse, self.org, name=name)

        rows = "\n".join(f"TW-{i},Item {i},100,WH-{i}" for i in range(TWINS))
        res = _post(
            self.client, "products",
            "sku,name,selling_price,warehouse\n" + rows + "\n",
        )
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["errors"], [], msg=str(res.data))
        self.assertEqual(res.data["warehouses_created"], 0)

        for name, (deleted, live) in pairs.items():
            deleted.refresh_from_db()
            live.refresh_from_db()
            self.assertTrue(deleted.is_deleted, f"{name}: deleted twin was revived")
            self.assertFalse(live.is_deleted, name)
            self.assertEqual(
                Warehouse.objects.filter(organisation=self.org, name=name).count(), 1, name,
            )

    def test_purchase_order_import_uses_the_live_warehouse_not_the_deleted_twin(self):
        Supplier.objects.create(organisation=self.org, name="Twin Supplier")
        Product.objects.create(
            organisation=self.org, sku="TW-SKU", name="Widget",
            product_type="physical", cost_price=1, selling_price=2,
        )
        pairs = {}
        for i in range(TWINS):
            name = f"POWH-{i}"
            pairs[name] = _make_twin(Warehouse, self.org, name=name)

        rows = "\n".join(
            f"PO-TW-{i},Twin Supplier,POWH-{i},2026-01-10,TW-SKU,5,100.00" for i in range(TWINS)
        )
        res = _post(
            self.client, "purchase_orders",
            "po_number,supplier_name,warehouse_name,order_date,product_sku,quantity,unit_cost\n"
            + rows + "\n",
        )
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["errors"], [], msg=str(res.data))
        self.assertEqual(res.data["purchase_orders_created"], TWINS, msg=str(res.data))
        self.assertEqual(res.data["warehouses_created"], 0)

        for i, (name, (deleted, live)) in enumerate(pairs.items()):
            deleted.refresh_from_db()
            self.assertTrue(deleted.is_deleted, f"{name}: deleted twin was revived")
            po = PurchaseOrder.objects.get(po_number=f"PO-TW-{i}")
            self.assertEqual(po.warehouse_id, live.pk, name)


class ProductTwinTests(TestCase):

    def setUp(self):
        _setup(self, "pr")

    def test_products_import_updates_the_live_product_not_the_deleted_twin(self):
        pairs = {}
        for i in range(TWINS):
            sku = f"TP-{i}"
            pairs[sku] = _make_twin(
                Product, self.org, sku=sku, name=f"Old {i}",
                product_type="physical", cost_price=1, selling_price=2,
            )

        rows = "\n".join(f"TP-{i},New {i},500" for i in range(TWINS))
        res = _post(self.client, "products", "sku,name,selling_price\n" + rows + "\n")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["errors"], [], msg=str(res.data))
        self.assertEqual(res.data["created"], 0)
        self.assertEqual(res.data["updated"], TWINS)

        for sku, (deleted, live) in pairs.items():
            deleted.refresh_from_db()
            live.refresh_from_db()
            self.assertTrue(deleted.is_deleted, f"{sku}: deleted twin was revived")
            self.assertEqual(live.name, f"New {sku[3:]}", sku)
            self.assertEqual(
                Product.objects.filter(organisation=self.org, sku=sku).count(), 1, sku,
            )

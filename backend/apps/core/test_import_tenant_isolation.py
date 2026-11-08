"""
Tenant isolation for the CSV importers that look records up by NAME.

The purchase-order importer now creates a missing warehouse by name, and the
supplier importer matches a blank-code row to an existing supplier by name.
Both are lookups keyed on text a user types, so the thing to prove is that a
name held by organisation A is invisible to organisation B: B must get its own
record, A's record must be untouched, and nothing may be revived across the
tenant line.
"""

from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounting.tests import _upgrade_to_business
from apps.authentication.models import User
from apps.inventory.models import Product, Warehouse
from apps.purchases.models import PurchaseOrder
from apps.suppliers.models import Supplier
from apps.tenancy.services import OrganisationService


def _tenant(tag):
    user = User.objects.create_user(
        email=f"iso_{tag}@example.com", password="TestPass123!",
        first_name="Iso", last_name=tag, is_verified=True,
    )
    org = OrganisationService.create_organisation(
        name=f"Isolation {tag}", owner=user,
        extra={"currency": "NGN", "country": "NG"},
    )
    _upgrade_to_business(org)
    client = APIClient()
    client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {str(RefreshToken.for_user(user).access_token)}",
        HTTP_X_ORGANISATION_ID=str(org.id),
    )
    return org, client


def _post(client, entity, text):
    up = SimpleUploadedFile(f"{entity}.csv", text.encode("utf-8"), content_type="text/csv")
    return client.post(f"/api/v1/import/{entity}/", {"file": up}, format="multipart")


PO_CSV = (
    "po_number,supplier_name,warehouse_name,order_date,product_sku,quantity,unit_cost\n"
    "PO-ISO-1,Shared Supplier,Shared Warehouse,2026-01-10,SHARED-SKU,5,100.00\n"
)


class PurchaseOrderImportTenantIsolationTests(TestCase):

    def setUp(self):
        self.org_a, self.client_a = _tenant("a")
        self.org_b, self.client_b = _tenant("b")

        # Organisation A already holds every name the file mentions.
        self.wh_a = Warehouse.objects.create(organisation=self.org_a, name="Shared Warehouse")
        self.sup_a = Supplier.objects.create(organisation=self.org_a, name="Shared Supplier")
        self.prod_a = Product.objects.create(
            organisation=self.org_a, sku="SHARED-SKU", name="A widget",
            product_type="physical", cost_price=1, selling_price=2,
        )

    def _give_b_supplier_and_product(self):
        Supplier.objects.create(organisation=self.org_b, name="Shared Supplier")
        Product.objects.create(
            organisation=self.org_b, sku="SHARED-SKU", name="B widget",
            product_type="physical", cost_price=1, selling_price=2,
        )

    def test_warehouse_held_by_another_org_is_not_reused(self):
        self._give_b_supplier_and_product()

        res = _post(self.client_b, "purchase_orders", PO_CSV)
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["errors"], [], msg=str(res.data))
        self.assertEqual(res.data["warehouses_created"], 1)

        b_wh = Warehouse.all_objects.filter(organisation=self.org_b, name="Shared Warehouse")
        self.assertEqual(b_wh.count(), 1, "B must get its own warehouse")
        self.assertNotEqual(b_wh.first().pk, self.wh_a.pk)

        po = PurchaseOrder.objects.get(po_number="PO-ISO-1")
        self.assertEqual(po.organisation_id, self.org_b.id)
        self.assertEqual(po.warehouse_id, b_wh.first().pk)
        self.assertNotEqual(po.warehouse_id, self.wh_a.pk)

        self.wh_a.refresh_from_db()
        self.assertEqual(self.wh_a.organisation_id, self.org_a.id)
        self.assertEqual(
            Warehouse.all_objects.filter(organisation=self.org_a, name="Shared Warehouse").count(), 1,
        )

    def test_soft_deleted_warehouse_in_another_org_is_not_revived(self):
        self.wh_a.is_deleted = True
        self.wh_a.deleted_at = timezone.now()
        self.wh_a.is_active = False
        self.wh_a.save()
        self._give_b_supplier_and_product()

        res = _post(self.client_b, "purchase_orders", PO_CSV)
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["errors"], [], msg=str(res.data))

        self.wh_a.refresh_from_db()
        self.assertTrue(self.wh_a.is_deleted, "A's deleted warehouse must stay deleted")
        self.assertFalse(self.wh_a.is_active)
        self.assertEqual(self.wh_a.organisation_id, self.org_a.id)

    def test_supplier_and_product_of_another_org_are_not_matched(self):
        # B has NO supplier or product of those names, so A's must not satisfy the lookup.
        res = _post(self.client_b, "purchase_orders", PO_CSV)
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["purchase_orders_created"], 0)
        fields = {e["field"] for e in res.data["errors"]}
        self.assertIn("supplier_name", fields)
        self.assertFalse(PurchaseOrder.objects.filter(po_number="PO-ISO-1").exists())
        # A failed file must not leave a warehouse behind in B either.
        self.assertFalse(
            Warehouse.all_objects.filter(organisation=self.org_b, name="Shared Warehouse").exists(),
        )


class SupplierImportTenantIsolationTests(TestCase):

    def test_blank_code_row_does_not_match_another_orgs_supplier_by_name(self):
        org_a, _ = _tenant("sa")
        org_b, client_b = _tenant("sb")
        sup_a = Supplier.objects.create(organisation=org_a, name="Kobo Trading", code="KOB-A")

        # Every data row needs two filled cells or _parse_csv silently drops it.
        res = _post(
            client_b, "suppliers",
            "name,code,contact_person\nKobo Trading,,Mr Okoro\nOther Co,,Ms Ade\n",
        )
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["created"], 2, msg=str(res.data))
        self.assertEqual(res.data["updated"], 0)

        sup_a.refresh_from_db()
        self.assertEqual(sup_a.organisation_id, org_a.id)
        self.assertEqual(sup_a.code, "KOB-A")
        self.assertEqual(Supplier.all_objects.filter(organisation=org_a).count(), 1)
        self.assertEqual(
            Supplier.all_objects.filter(organisation=org_b, name="Kobo Trading").count(), 1,
        )

    def test_soft_deleted_supplier_in_another_org_is_not_revived(self):
        org_a, _ = _tenant("sc")
        org_b, client_b = _tenant("sd")
        sup_a = Supplier.objects.create(organisation=org_a, name="Gone Ltd", code="GON-A")
        sup_a.is_deleted = True
        sup_a.deleted_at = timezone.now()
        sup_a.save()

        res = _post(client_b, "suppliers", "name,code,contact_person\nGone Ltd,,Mr Okoro\n")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["created"], 1, msg=str(res.data))

        sup_a.refresh_from_db()
        self.assertTrue(sup_a.is_deleted, "A's deleted supplier must stay deleted")
        self.assertEqual(sup_a.organisation_id, org_a.id)

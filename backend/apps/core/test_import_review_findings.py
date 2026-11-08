"""
Edge cases found in review of the import fixes, pinned so they cannot return.

* A blank-code supplier row must not guess between several same-named suppliers.
* Reviving a deleted supplier whose code a live supplier now holds must not
  crash the import.
* Reviving a deleted warehouse must not take the default flag from the
  warehouse that is the default now.
* A purchase order or budget file with any bad row writes nothing, as the
  importers promise, instead of saving the good lines of a half-bad record.
"""

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounting.tests import _upgrade_to_business
from apps.authentication.models import User
from apps.budgets.models import Budget
from apps.inventory.models import Product, Warehouse
from apps.purchases.models import PurchaseOrder
from apps.suppliers.models import Supplier
from apps.tenancy.services import OrganisationService


def _setup(test, tag):
    user = User.objects.create_user(
        email=f"rf_{tag}@example.com", password="TestPass123!",
        first_name="Review", last_name=tag, is_verified=True,
    )
    test.org = OrganisationService.create_organisation(
        name=f"Review {tag}", owner=user, extra={"currency": "NGN", "country": "NG"},
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


def _delete(obj):
    obj.is_deleted = True
    obj.deleted_at = timezone.now()
    obj.save()


class SupplierReviewFindingTests(TestCase):

    def setUp(self):
        _setup(self, "sup")

    def test_blank_code_row_is_refused_when_two_suppliers_share_the_name(self):
        a = Supplier.objects.create(organisation=self.org, name="Twin Co", code="TW-1", contact_person="First")
        b = Supplier.objects.create(organisation=self.org, name="Twin Co", code="TW-2", contact_person="Second")

        res = _post(self.client, "suppliers", "name,code,contact_person\nTwin Co,,Changed\n")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["created"], 0, msg=str(res.data))
        self.assertEqual(res.data["updated"], 0, msg=str(res.data))
        self.assertEqual([e["field"] for e in res.data["errors"]], ["code"], msg=str(res.data))

        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual((a.contact_person, b.contact_person), ("First", "Second"))
        self.assertEqual(Supplier.objects.filter(organisation=self.org).count(), 2)

    def test_the_same_row_with_a_code_still_updates_the_right_supplier(self):
        a = Supplier.objects.create(organisation=self.org, name="Twin Co", code="TW-1", contact_person="First")
        Supplier.objects.create(organisation=self.org, name="Twin Co", code="TW-2", contact_person="Second")

        res = _post(self.client, "suppliers", "name,code,contact_person\nTwin Co,TW-1,Changed\n")
        self.assertEqual(res.data["errors"], [], msg=str(res.data))
        self.assertEqual(res.data["updated"], 1)
        a.refresh_from_db()
        self.assertEqual(a.contact_person, "Changed")

    def test_reviving_a_supplier_whose_code_was_taken_gets_a_fresh_code(self):
        old = Supplier.all_objects.create(organisation=self.org, name="Old Co", code="OLD-1")
        _delete(old)
        other = Supplier.objects.create(organisation=self.org, name="Other Co", code="OLD-1")

        res = _post(self.client, "suppliers", "name,code,contact_person\nOld Co,,Mr Okoro\n")
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["errors"], [], msg=str(res.data))
        self.assertEqual(res.data["updated"], 1, msg=str(res.data))

        old.refresh_from_db()
        other.refresh_from_db()
        self.assertFalse(old.is_deleted)
        self.assertNotEqual(old.code, "OLD-1")
        self.assertEqual((other.name, other.code), ("Other Co", "OLD-1"))


class WarehouseDefaultReviewFindingTests(TestCase):

    def setUp(self):
        _setup(self, "wh")
        # A deleted former default, then the live default that replaced it.
        # Warehouse.save() only demotes LIVE rows, so the deleted one keeps its flag.
        self.old = Warehouse.all_objects.create(
            organisation=self.org, name="Old Depot", is_default=True,
            is_deleted=True, deleted_at=timezone.now(), is_active=False,
        )
        self.main = Warehouse.objects.create(organisation=self.org, name="Main", is_default=True)

    def _assert_default_untouched(self):
        self.old.refresh_from_db()
        self.main.refresh_from_db()
        self.assertFalse(self.old.is_deleted, "the named warehouse should be back")
        self.assertFalse(self.old.is_default, "a revived warehouse must not take the default")
        self.assertTrue(self.main.is_default, "the current default must stay the default")

    def test_products_import_does_not_hand_the_default_to_a_revived_warehouse(self):
        res = _post(
            self.client, "products",
            "sku,name,selling_price,warehouse\nRD-1,Item,100,Old Depot\n",
        )
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["errors"], [], msg=str(res.data))
        self._assert_default_untouched()

    def test_purchase_order_import_does_not_hand_the_default_to_a_revived_warehouse(self):
        Supplier.objects.create(organisation=self.org, name="Dep Supplier")
        Product.objects.create(
            organisation=self.org, sku="RD-2", name="Widget",
            product_type="physical", cost_price=1, selling_price=2,
        )
        res = _post(
            self.client, "purchase_orders",
            "po_number,supplier_name,warehouse_name,order_date,product_sku,quantity,unit_cost\n"
            "PO-RD-1,Dep Supplier,Old Depot,2026-01-10,RD-2,5,100.00\n",
        )
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual(res.data["errors"], [], msg=str(res.data))
        self._assert_default_untouched()


class AllOrNothingReviewFindingTests(TestCase):

    PO_HEADER = "po_number,supplier_name,warehouse_name,order_date,product_sku,quantity,unit_cost\n"

    def setUp(self):
        _setup(self, "aon")
        Supplier.objects.create(organisation=self.org, name="Good Supplier")
        Product.objects.create(
            organisation=self.org, sku="GOOD-1", name="Widget",
            product_type="physical", cost_price=1, selling_price=2,
        )

    def test_a_purchase_order_with_one_bad_line_writes_nothing(self):
        bad = (
            self.PO_HEADER
            + "PO-AON-1,Good Supplier,Brand New Depot,2026-01-10,GOOD-1,5,100.00\n"
            + "PO-AON-1,Good Supplier,Brand New Depot,2026-01-10,NO-SUCH-SKU,2,50.00\n"
        )
        res = _post(self.client, "purchase_orders", bad)
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual([e["field"] for e in res.data["errors"]], ["product_sku"], msg=str(res.data))
        self.assertEqual(res.data["purchase_orders_created"], 0, msg=str(res.data))
        self.assertFalse(PurchaseOrder.objects.filter(po_number="PO-AON-1").exists(), "no half-built PO")
        self.assertFalse(
            Warehouse.all_objects.filter(organisation=self.org, name="Brand New Depot").exists(),
            "a rejected file must not leave a warehouse behind",
        )

        # The corrected file must then import in full, not be skipped as existing.
        good = (
            self.PO_HEADER
            + "PO-AON-1,Good Supplier,Brand New Depot,2026-01-10,GOOD-1,5,100.00\n"
            + "PO-AON-1,Good Supplier,Brand New Depot,2026-01-10,GOOD-1,2,50.00\n"
        )
        res = _post(self.client, "purchase_orders", good)
        self.assertEqual(res.data["errors"], [], msg=str(res.data))
        self.assertEqual(res.data["purchase_orders_created"], 1, msg=str(res.data))
        self.assertEqual(PurchaseOrder.objects.get(po_number="PO-AON-1").items.count(), 2)

    def test_an_over_long_warehouse_name_is_a_row_error_not_a_crash(self):
        long_name = "W" * 201
        res = _post(
            self.client, "purchase_orders",
            self.PO_HEADER + f"PO-AON-2,Good Supplier,{long_name},2026-01-10,GOOD-1,5,100.00\n",
        )
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertEqual([e["field"] for e in res.data["errors"]], ["warehouse_name"], msg=str(res.data))
        self.assertFalse(PurchaseOrder.objects.filter(po_number="PO-AON-2").exists())

    def test_a_budget_with_one_bad_line_writes_nothing(self):
        bad = (
            "budget_name,fiscal_year,category_name,category_type,budgeted_amount\n"
            "AON Budget,2026,Sales,revenue,100\n"
            "AON Budget,2026,Rent,not_a_type,50\n"
        )
        res = _post(self.client, "budgets", bad)
        self.assertEqual(res.status_code, 200, msg=str(res.data))
        self.assertTrue(res.data["errors"], msg=str(res.data))
        self.assertEqual(res.data["budgets_created"], 0, msg=str(res.data))
        self.assertFalse(Budget.objects.filter(organisation=self.org, name="AON Budget").exists())

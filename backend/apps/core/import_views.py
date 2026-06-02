"""
CSV bulk-import endpoints.

POST /api/v1/import/products/   — multipart form with `file` field (CSV)
POST /api/v1/import/customers/  — multipart form with `file` field (CSV)
POST /api/v1/import/accounts/   — multipart form with `file` field (CSV)
GET  /api/v1/import/template/<entity>/  — download a CSV template

All endpoints require authentication and a valid X-Organisation-ID header.
Only managers and above can use import endpoints (IsManagerOrSuperuser).
"""

import csv
import io
from decimal import Decimal, InvalidOperation

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsManagerOrSuperuser, IsVerified, _get_or_resolve_org


# ---------------------------------------------------------------------------
# CSV column definitions (required / optional) per entity
# ---------------------------------------------------------------------------

PRODUCT_REQUIRED = ["sku", "name", "selling_price", "cost_price"]
PRODUCT_OPTIONAL = [
    "product_type", "category", "brand", "unit_of_measure",
    "reorder_level", "barcode", "description",
    "warehouse", "opening_stock",
]
PRODUCT_ALL = PRODUCT_REQUIRED + PRODUCT_OPTIONAL

CUSTOMER_REQUIRED = ["code", "name"]
CUSTOMER_OPTIONAL = [
    "customer_type", "email", "phone", "address",
    "contact_person", "credit_limit", "payment_terms_days", "notes",
]
CUSTOMER_ALL = CUSTOMER_REQUIRED + CUSTOMER_OPTIONAL

ACCOUNT_REQUIRED = ["code", "name", "account_type"]
ACCOUNT_OPTIONAL = ["description"]
ACCOUNT_ALL = ACCOUNT_REQUIRED + ACCOUNT_OPTIONAL

VALID_ACCOUNT_TYPES = [
    "asset", "liability", "equity", "revenue",
    "expense", "cost_of_goods",
]

PRODUCT_TYPES = ["physical", "service", "digital"]
UNITS = ["bottle", "carton", "case", "litre", "unit", "hour", "day", "kg", "piece"]
CUSTOMER_TYPES = [
    "retail", "wholesale", "distributor", "corporate",
    "client", "passenger", "vip", "government", "ngo",
]

CSV_ROW_LIMIT = 10_000


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _parse_csv(file_obj):
    """Return (headers, rows) where rows is a list of dicts. Raises ValueError if over limit."""
    text = file_obj.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    if len(rows) > CSV_ROW_LIMIT:
        raise ValueError(
            f"CSV exceeds the {CSV_ROW_LIMIT:,}-row limit ({len(rows):,} rows found). "
            "Split the file into smaller batches and re-import."
        )
    headers = reader.fieldnames or []
    return [h.strip().lower() for h in headers], [
        {k.strip().lower(): (v or "").strip() for k, v in row.items()} for row in rows
    ]


def _money(val, field, errors, row_num):
    """Parse a money string; append to errors on failure."""
    try:
        return Decimal(str(val).replace(",", ""))
    except InvalidOperation:
        errors.append({"row": row_num, "field": field, "message": f"Invalid number '{val}'"})
        return None


def _int_val(val, field, errors, row_num, default=0):
    try:
        return int(val) if val else default
    except (ValueError, TypeError):
        errors.append({"row": row_num, "field": field, "message": f"Invalid integer '{val}'"})
        return None


def _missing_required(row, required, errors, row_num):
    for col in required:
        if not row.get(col):
            errors.append({"row": row_num, "field": col, "message": "Required field is empty"})
    return any(not row.get(col) for col in required)


# ---------------------------------------------------------------------------
# Products import
# ---------------------------------------------------------------------------

class ImportProductsView(APIView):
    permission_classes = [IsAuthenticated, IsVerified, IsManagerOrSuperuser]

    def post(self, request):
        org = _get_or_resolve_org(request)
        if not org:
            return Response({"error": "Organisation not found"}, status=400)

        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"error": "No file uploaded"}, status=400)

        try:
            headers, rows = _parse_csv(file_obj)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        missing_cols = [c for c in PRODUCT_REQUIRED if c not in headers]
        if missing_cols:
            return Response(
                {"error": f"CSV missing required columns: {', '.join(missing_cols)}"},
                status=400,
            )

        from decimal import Decimal as D
        from apps.inventory.models import Product, Category, Warehouse
        from apps.inventory.services import InventoryService
        from django.db import transaction

        has_warehouse_col = "warehouse" in headers
        created = 0
        updated = 0
        stock_assigned = 0
        warehouses_created = 0
        errors = []

        # Pre-build warehouse cache to avoid N+1 lookups
        warehouse_cache: dict = {}

        def _get_or_create_warehouse(name: str):
            key = name.strip().lower()
            if key in warehouse_cache:
                return warehouse_cache[key]
            wh, wh_new = Warehouse.objects.get_or_create(
                organisation=org,
                name__iexact=name,
                defaults={"name": name.strip(), "organisation": org, "is_active": True},
            )
            warehouse_cache[key] = (wh, wh_new)
            return wh, wh_new

        for idx, row in enumerate(rows, start=2):
            row_num = idx
            if _missing_required(row, PRODUCT_REQUIRED, errors, row_num):
                continue

            selling_price = _money(row["selling_price"], "selling_price", errors, row_num)
            cost_price = _money(row["cost_price"], "cost_price", errors, row_num)
            if selling_price is None or cost_price is None:
                continue

            product_type = row.get("product_type", "physical").lower()
            if product_type not in PRODUCT_TYPES:
                product_type = "physical"

            unit = row.get("unit_of_measure", "unit").lower()
            if unit not in UNITS:
                unit = "unit"

            reorder_level = _int_val(row.get("reorder_level", "10"), "reorder_level", errors, row_num, 10)
            if reorder_level is None:
                reorder_level = 10

            category = None
            if row.get("category"):
                category, _ = Category.objects.get_or_create(
                    organisation=org,
                    name__iexact=row["category"],
                    defaults={"name": row["category"], "organisation": org},
                )

            obj, was_created = Product.objects.update_or_create(
                organisation=org,
                sku=row["sku"],
                defaults={
                    "name": row["name"],
                    "product_type": product_type,
                    "selling_price": selling_price,
                    "cost_price": cost_price,
                    "brand": row.get("brand", ""),
                    "unit_of_measure": unit,
                    "reorder_level": reorder_level,
                    "barcode": row.get("barcode", ""),
                    "description": row.get("description", ""),
                    "category": category,
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

            # ── Warehouse + opening stock ─────────────────────────────────────
            if has_warehouse_col and product_type == "physical":
                wh_name = row.get("warehouse", "").strip()
                qty_raw = row.get("opening_stock", "").strip()
                qty = D("0")
                if qty_raw:
                    try:
                        qty = D(qty_raw.replace(",", ""))
                    except Exception:
                        errors.append({"row": row_num, "field": "opening_stock",
                                       "message": f"Invalid number '{qty_raw}'"})

                if wh_name:
                    try:
                        wh, wh_new = _get_or_create_warehouse(wh_name)
                        if wh_new:
                            warehouses_created += 1
                        if qty > 0:
                            with transaction.atomic():
                                InventoryService.adjust_stock(
                                    organisation=org,
                                    product=obj,
                                    warehouse=wh,
                                    quantity=qty,
                                    reason="Opening stock — CSV import",
                                    created_by=request.user,
                                )
                            stock_assigned += 1
                    except Exception as exc:
                        errors.append({"row": row_num, "field": "warehouse",
                                       "message": str(exc)})

        response_data = {
            "created": created,
            "updated": updated,
            "errors": errors,
            "total_rows": len(rows),
        }
        if has_warehouse_col:
            response_data["warehouses_created"] = warehouses_created
            response_data["stock_assigned"] = stock_assigned
        return Response(response_data)


# ---------------------------------------------------------------------------
# Customers import
# ---------------------------------------------------------------------------

class ImportCustomersView(APIView):
    permission_classes = [IsAuthenticated, IsVerified, IsManagerOrSuperuser]

    def post(self, request):
        org = _get_or_resolve_org(request)
        if not org:
            return Response({"error": "Organisation not found"}, status=400)

        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"error": "No file uploaded"}, status=400)

        try:
            headers, rows = _parse_csv(file_obj)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        missing_cols = [c for c in CUSTOMER_REQUIRED if c not in headers]
        if missing_cols:
            return Response(
                {"error": f"CSV missing required columns: {', '.join(missing_cols)}"},
                status=400,
            )

        from apps.customers.models import Customer

        created = 0
        updated = 0
        errors = []

        for idx, row in enumerate(rows, start=2):
            row_num = idx
            if _missing_required(row, CUSTOMER_REQUIRED, errors, row_num):
                continue

            customer_type = row.get("customer_type", "retail").lower()
            if customer_type not in CUSTOMER_TYPES:
                customer_type = "retail"

            credit_limit = Decimal("0")
            if row.get("credit_limit"):
                v = _money(row["credit_limit"], "credit_limit", errors, row_num)
                if v is None:
                    continue
                credit_limit = v

            payment_terms = _int_val(row.get("payment_terms_days", "0"), "payment_terms_days", errors, row_num, 0)
            if payment_terms is None:
                payment_terms = 0

            obj, was_created = Customer.objects.update_or_create(
                organisation=org,
                code=row["code"],
                defaults={
                    "name": row["name"],
                    "customer_type": customer_type,
                    "email": row.get("email", ""),
                    "phone": row.get("phone", ""),
                    "address": row.get("address", ""),
                    "contact_person": row.get("contact_person", ""),
                    "credit_limit": credit_limit,
                    "payment_terms_days": payment_terms,
                    "notes": row.get("notes", ""),
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        return Response({
            "created": created,
            "updated": updated,
            "errors": errors,
            "total_rows": len(rows),
        })


# ---------------------------------------------------------------------------
# Chart of Accounts import
# ---------------------------------------------------------------------------

class ImportAccountsView(APIView):
    permission_classes = [IsAuthenticated, IsVerified, IsManagerOrSuperuser]

    def post(self, request):
        org = _get_or_resolve_org(request)
        if not org:
            return Response({"error": "Organisation not found"}, status=400)

        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"error": "No file uploaded"}, status=400)

        try:
            headers, rows = _parse_csv(file_obj)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        missing_cols = [c for c in ACCOUNT_REQUIRED if c not in headers]
        if missing_cols:
            return Response(
                {"error": f"CSV missing required columns: {', '.join(missing_cols)}"},
                status=400,
            )

        from apps.accounting.models import Account

        created = 0
        updated = 0
        errors = []

        for idx, row in enumerate(rows, start=2):
            row_num = idx
            if _missing_required(row, ACCOUNT_REQUIRED, errors, row_num):
                continue

            account_type = row["account_type"].lower().replace(" ", "_")
            if account_type not in VALID_ACCOUNT_TYPES:
                errors.append({
                    "row": row_num,
                    "field": "account_type",
                    "message": f"Invalid account_type '{row['account_type']}'. Must be one of: {', '.join(VALID_ACCOUNT_TYPES)}",
                })
                continue

            obj, was_created = Account.objects.update_or_create(
                organisation=org,
                code=row["code"],
                defaults={
                    "name": row["name"],
                    "account_type": account_type,
                    "description": row.get("description", ""),
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        return Response({
            "created": created,
            "updated": updated,
            "errors": errors,
            "total_rows": len(rows),
        })


# ---------------------------------------------------------------------------
# Template download
# ---------------------------------------------------------------------------

TEMPLATES = {
    "products": PRODUCT_ALL,
    "customers": CUSTOMER_ALL,
    "accounts": ACCOUNT_ALL,
}

SAMPLE_ROWS = {
    "products": [
        ["SKU001", "Hennessy VS 750ml", "5500.00", "3200.00", "physical", "Cognac", "Hennessy", "bottle", "10", "", "", "Main Warehouse", "24"],
        ["SKU002", "Delivery Service", "2000.00", "0.00", "service", "Logistics", "", "hour", "0", "", "Delivery service charge", "", ""],
    ],
    "customers": [
        ["CUST001", "Adaeze Okafor", "retail", "adaeze@example.com", "08012345678", "Lagos", "Adaeze", "0", "0", ""],
        ["CUST002", "Zenith Foods Ltd", "wholesale", "accounts@zenith.ng", "08087654321", "Abuja", "Mr Bello", "500000", "30", "Preferred supplier"],
    ],
    "accounts": [
        ["6000", "Office Supplies", "expense", "General office supplies expense"],
        ["1050", "Petty Cash", "asset", "Petty cash on hand"],
    ],
}


class ImportTemplateView(APIView):
    permission_classes = [IsAuthenticated, IsVerified]

    def get(self, request, entity):
        from django.http import HttpResponse

        if entity not in TEMPLATES:
            return Response({"error": f"Unknown entity '{entity}'. Choose: products, customers, accounts"}, status=400)

        columns = TEMPLATES[entity]
        sample_rows = SAMPLE_ROWS.get(entity, [])

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(columns)
        for row in sample_rows:
            # Pad row to match column count
            padded = row + [""] * (len(columns) - len(row))
            writer.writerow(padded[:len(columns)])

        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{entity}_import_template.csv"'
        return response

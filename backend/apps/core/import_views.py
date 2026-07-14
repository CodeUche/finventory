"""
CSV bulk-import endpoints.

POST /api/v1/import/products/        — multipart form with `file` field (CSV)
POST /api/v1/import/customers/       — multipart form with `file` field (CSV)
POST /api/v1/import/accounts/        — multipart form with `file` field (CSV)
POST /api/v1/import/suggest-mapping/ — AI column-name mapper
GET  /api/v1/import/template/<entity>/ — download a CSV template

All endpoints require authentication and a valid X-Organisation-ID header.
Only managers and above can use import endpoints (IsManagerOrSuperuser).

AI column mapping uses Groq (same key as AI assistant) to intelligently map
non-standard column names (e.g. "Retail selling price") to our canonical field
names (e.g. "selling_price"). Rule-based aliases are tried first; Groq is called
only for headers that don't match any known alias.
"""

import csv
import io
import json
from decimal import Decimal, InvalidOperation

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsManagerOrSuperuser, IsVerified, _get_or_resolve_org


# ---------------------------------------------------------------------------
# Column definitions per entity
# ---------------------------------------------------------------------------

# Products: all fields are optional — AI mapping + sensible defaults cover gaps.
PRODUCT_REQUIRED = []
PRODUCT_OPTIONAL = [
    "sku", "name", "selling_price", "cost_price", "wholesale_price",
    "product_type", "category", "brand", "unit_of_measure",
    "reorder_level", "barcode", "description",
    "warehouse", "opening_stock",
]
PRODUCT_ALL = PRODUCT_OPTIONAL  # kept for template generation order

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

# Per-organisation rolling daily cap across all import endpoints — stops a
# single org from flooding the DB with repeated max-size CSV uploads.
DAILY_IMPORT_ROW_QUOTA = 50_000


def _check_import_quota(org, row_count):
    """Return (allowed, rows_used_today). Increments usage if allowed."""
    from django.core.cache import cache
    from django.utils import timezone

    key = f"import_quota:{org.id}:{timezone.now().date()}"
    used = cache.get(key, 0)
    if used + row_count > DAILY_IMPORT_ROW_QUOTA:
        return False, used
    cache.set(key, used + row_count, timeout=60 * 60 * 26)
    return True, used

# ---------------------------------------------------------------------------
# Known column aliases for rule-based matching (before calling AI)
# Format: { our_canonical_field: [list of known aliases, all lowercase] }
# ---------------------------------------------------------------------------

PRODUCT_ALIASES = {
    "sku": [
        "sku", "product code", "item code", "code", "product id", "item id",
        "stock code", "part number", "part no", "ref", "item ref", "product ref",
        "article number", "article no", "product number",
    ],
    "name": [
        "name", "product name", "item name", "product title", "title",
        "item description", "product description", "goods name", "goods",
        "description",  # inventory/stock reports often use "Description" as the product name
    ],
    "selling_price": [
        "selling_price", "selling price", "sale price", "retail price",
        "retail selling price", "price", "unit price", "mrp", "list price",
        "customer price", "vat price", "inclusive price",
    ],
    "cost_price": [
        "cost_price", "cost price", "cost", "purchase price", "buy price",
        "supply price", "supplier price", "landed cost", "net price",
    ],
    "wholesale_price": [
        "wholesale_price", "wholesale price", "wholesale selling price",
        "whole sale price", "whole sale selling price",  # common spelling variants
        "trade price", "bulk price", "distributor price", "dealer price",
    ],
    "product_type": ["product_type", "product type", "type", "item type", "goods type"],
    "category": [
        "category", "product category", "category name", "dept", "department",
        "item category", "group", "product group",
    ],
    "brand": ["brand", "brand name", "manufacturer", "make", "supplier brand"],
    "unit_of_measure": [
        "unit_of_measure", "unit", "uom", "unit of measure", "measure",
        "unit of sale", "sales unit", "unit of ms.", "unit of ms", "unit ms",
    ],
    "reorder_level": [
        "reorder_level", "reorder level", "reorder point", "minimum stock",
        "min stock", "low stock threshold", "reorder qty",
    ],
    "barcode": ["barcode", "bar code", "upc", "ean", "gtin", "isbn", "scan code"],
    "description": [
        "description", "details", "notes", "remarks", "product details",
        "item notes", "long description",
    ],
    "warehouse": [
        "warehouse", "warehouse name", "location", "store", "storage",
        "stock location", "bin", "depot",
    ],
    "opening_stock": [
        "opening_stock", "opening stock", "initial stock", "quantity",
        "qty", "stock quantity", "on hand", "stock on hand", "stock level",
        "current stock", "available qty",
    ],
}


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _parse_csv(file_obj):
    """
    Parse CSV with smart header detection.

    Handles exported spreadsheets that have title rows, blank rows, or store/section
    headers before the actual column headers (e.g. stock availability reports).

    Returns (headers_lower, rows):
      - headers_lower: deduplicated, lowercased, non-empty column names
      - rows: list of dicts keyed by those headers
    """
    text = file_obj.read().decode("utf-8-sig")
    raw_reader = csv.reader(io.StringIO(text))
    all_rows = [row for row in raw_reader]

    if not all_rows:
        raise ValueError("CSV file is empty")

    # Find the actual header row: first row that has 3 or more non-empty cells.
    # This skips blank rows, single-cell title rows ("STOCK AVAILABILITY REPORT"),
    # and single-cell store/section rows ("Store: DREAM WINE STORE").
    header_idx = 0
    for i, row in enumerate(all_rows):
        if sum(1 for c in row if c.strip()) >= 3:
            header_idx = i
            break

    raw_headers = all_rows[header_idx]

    # Build column index: position → lowercase header, skipping blanks and duplicates
    col_map: dict[int, str] = {}
    seen: set[str] = set()
    for j, h in enumerate(raw_headers):
        h_clean = h.strip().lower()
        if h_clean and h_clean not in seen:
            col_map[j] = h_clean
            seen.add(h_clean)

    headers_lower = list(col_map.values())
    max_col = max(col_map.keys(), default=0)

    # Build row dicts; skip rows with fewer than 2 non-empty cells (blank lines,
    # section headers like "Store: X", serial-number-only rows, etc.)
    rows: list[dict] = []
    for raw_row in all_rows[header_idx + 1:]:
        if sum(1 for c in raw_row if c.strip()) < 2:
            continue
        padded = raw_row + [""] * max(0, max_col + 1 - len(raw_row))
        row_dict = {col_map[j]: padded[j].strip() for j in col_map}
        rows.append(row_dict)

    if len(rows) > CSV_ROW_LIMIT:
        raise ValueError(
            f"CSV exceeds the {CSV_ROW_LIMIT:,}-row limit ({len(rows):,} rows found). "
            "Split the file into smaller batches and re-import."
        )

    return headers_lower, rows


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


def _normalize_ws(s: str) -> str:
    """Lowercase and collapse all whitespace to single spaces."""
    return " ".join(s.lower().split())


def _rule_based_mapping(csv_headers, aliases_dict):
    """
    Map CSV headers to canonical field names using the known-alias lookup.
    Normalises whitespace before comparison so 'Whole Sale  Selling Price'
    matches the alias 'whole sale selling price'.
    Returns { canonical_field: original_csv_header } for headers that matched.
    """
    # Build normalised → original mapping (first occurrence wins for duplicates)
    norm_to_original: dict[str, str] = {}
    for h in csv_headers:
        norm = _normalize_ws(h)
        if norm not in norm_to_original:
            norm_to_original[norm] = h

    mapping: dict[str, str] = {}
    used_csv_cols: set[str] = set()

    for our_field, aliases in aliases_dict.items():
        for alias in aliases:
            norm_alias = _normalize_ws(alias)
            if norm_alias in norm_to_original:
                original = norm_to_original[norm_alias]
                if original not in used_csv_cols:
                    mapping[our_field] = original
                    used_csv_cols.add(original)
                    break

    return mapping


def _groq_mapping(csv_headers, target_fields, already_mapped_csv_cols, api_key):
    """
    Call Groq to map remaining unmapped CSV headers to target fields.
    Returns { canonical_field: csv_header } for any newly found matches.
    """
    import re
    import requests as req

    unmapped_headers = [h for h in csv_headers if h not in already_mapped_csv_cols]
    unassigned_fields = [f for f in target_fields if f not in already_mapped_csv_cols.values() if f]

    if not unmapped_headers or not unassigned_fields:
        return {}

    prompt = (
        "You are a data-import assistant for a business inventory/stock management system.\n"
        f"Unmatched CSV columns: {unmapped_headers}\n"
        f"Target fields still needing a match: {unassigned_fields}\n\n"
        "Rules:\n"
        "- In stock/inventory reports, 'Description' usually means the PRODUCT NAME (map to 'name').\n"
        "- 'S/No', 'No.', 'Seq', 'Row' are serial numbers — do NOT map them to any field.\n"
        "- 'Unit of Ms.', 'UOM', 'Unit' → 'unit_of_measure'.\n"
        "- 'Qty', 'Quantity', 'Stock Qty', 'On Hand' → 'opening_stock'.\n"
        "- 'Whole Sale *' or 'Wholesale *' price columns → 'wholesale_price'.\n"
        "- 'Retail *' price columns → 'selling_price'.\n"
        "- Only map when confident. Each CSV column can only be used once.\n"
        "Return ONLY a JSON object: {\"target_field\": \"CSV Column\"}. No explanation."
    )

    try:
        resp = req.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [
                    {"role": "system", "content": "Return only valid JSON. No markdown, no explanation."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "max_tokens": 300,
            },
            timeout=8,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
        if match:
            result = json.loads(match.group())
            # Validate: only keep mappings where both field and csv col are valid
            validated = {}
            used = set()
            for field, csv_col in result.items():
                if (
                    field in unassigned_fields
                    and csv_col in unmapped_headers
                    and csv_col not in used
                ):
                    validated[field] = csv_col
                    used.add(csv_col)
            return validated
    except Exception:
        pass

    return {}


def _apply_column_mapping(rows, field_to_csv_col):
    """
    field_to_csv_col: { our_canonical_field: original_csv_header }
    _parse_csv already lowercased row keys, so we normalise csv header to lowercase when looking up.
    Adds canonical field keys to each row without overwriting existing direct matches.
    """
    if not field_to_csv_col:
        return rows

    # Normalise: our_field → lowercase csv col for row lookup
    norm = {
        our_field: csv_col.strip().lower()
        for our_field, csv_col in field_to_csv_col.items()
        if csv_col
    }

    result = []
    for row in rows:
        new_row = dict(row)
        for our_field, csv_col_lower in norm.items():
            # Only add alias if: (a) our canonical key isn't already in the row,
            # or (b) it is but it's blank (prefer the remapped value)
            if csv_col_lower in row and (our_field not in row or not row[our_field]):
                new_row[our_field] = row[csv_col_lower]
        result.append(new_row)
    return result


# ---------------------------------------------------------------------------
# Products import
# ---------------------------------------------------------------------------

class ImportProductsView(APIView):
    permission_classes = [IsAuthenticated, IsVerified, IsManagerOrSuperuser]

    def post(self, request):
        import logging as _log
        import uuid as _uuid
        from decimal import Decimal as D
        from django.db import transaction
        from apps.inventory.models import Category, Product, Warehouse
        from apps.inventory.services import InventoryService

        try:
            return self._do_import(request, _uuid, D, transaction, Category, Product, Warehouse, InventoryService)
        except Exception as exc:
            _log.getLogger(__name__).exception("CSV product import failed")
            return Response({"error": f"[{type(exc).__name__}] {exc}"}, status=422)

    def _do_import(self, request, _uuid, D, transaction, Category, Product, Warehouse, InventoryService):
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

        ok, used = _check_import_quota(org, len(rows))
        if not ok:
            return Response(
                {"error": f"Daily import quota exceeded ({DAILY_IMPORT_ROW_QUOTA:,} rows/day, {used:,} already used today). Try again tomorrow."},
                status=429,
            )

        # Parse optional column mapping supplied by the frontend
        mapping_raw = request.data.get("column_mapping", "{}")
        try:
            field_to_csv_col = json.loads(mapping_raw) if isinstance(mapping_raw, str) else (mapping_raw or {})
        except Exception:
            field_to_csv_col = {}

        # Apply mapping: add canonical field keys to each row
        rows = _apply_column_mapping(rows, field_to_csv_col)

        has_warehouse_col = "warehouse" in headers or any(
            v.strip().lower() == "warehouse" or
            (v and field_to_csv_col.get("warehouse", "").strip().lower() == v.strip().lower())
            for v in field_to_csv_col.values()
        ) or "warehouse" in [r.strip().lower() for r in field_to_csv_col.values() if r]
        # Simpler: just check if any row has a warehouse value after mapping
        has_warehouse_col = any(r.get("warehouse") for r in rows[:5]) or "warehouse" in headers

        created = 0
        updated = 0
        stock_assigned = 0
        warehouses_created = 0
        errors = []
        warehouse_cache: dict = {}

        def _get_or_create_warehouse(name: str):
            key = name.strip().lower()
            if key in warehouse_cache:
                return warehouse_cache[key]
            # Include soft-deleted rows (see the product lookup below) so a
            # previously deleted warehouse is revived rather than hitting the
            # (organisation, name) unique constraint on re-import.
            existing = Warehouse.all_objects.filter(organisation=org, name__iexact=name).first()
            if existing is not None:
                if existing.is_deleted:
                    existing.is_deleted = False
                    existing.deleted_at = None
                    existing.is_active = True
                    existing.save()
                wh, wh_new = existing, False
            else:
                wh = Warehouse.objects.create(organisation=org, name=name.strip(), is_active=True)
                wh_new = True
            warehouse_cache[key] = (wh, wh_new)
            return wh, wh_new

        for idx, row in enumerate(rows, start=2):
            row_num = idx

            # SKU: auto-generate if absent
            sku = row.get("sku", "").strip()
            if not sku:
                sku = f"AUTO-{str(_uuid.uuid4())[:8].upper()}"

            # Name: default to SKU if absent
            name = row.get("name", "").strip() or f"Product {sku}"

            # Prices: default to 0 if absent or unparseable
            selling_price_raw = row.get("selling_price", "0") or "0"
            cost_price_raw = row.get("cost_price", "0") or "0"
            wholesale_price_raw = row.get("wholesale_price", "0") or "0"

            selling_price = _money(selling_price_raw, "selling_price", errors, row_num)
            cost_price = _money(cost_price_raw, "cost_price", errors, row_num)
            wholesale_price = _money(wholesale_price_raw, "wholesale_price", errors, row_num)
            if selling_price is None:
                selling_price = D("0")
            if cost_price is None:
                cost_price = D("0")
            if wholesale_price is None:
                wholesale_price = D("0")

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

            defaults = {
                "name": name,
                "product_type": product_type,
                "selling_price": selling_price,
                "cost_price": cost_price,
                "wholesale_price": wholesale_price,
                "brand": row.get("brand", ""),
                "unit_of_measure": unit,
                "reorder_level": reorder_level,
                "barcode": row.get("barcode", ""),
                "description": row.get("description", ""),
                "category": category,
            }
            # Look up including soft-deleted rows. The (organisation, sku) unique
            # constraint is enforced at the DB level regardless of is_deleted, so a
            # previously "deleted" product still occupies that SKU. Reviving it on
            # re-import avoids a duplicate-key IntegrityError (products deleted then
            # re-imported).
            existing = Product.all_objects.filter(organisation=org, sku=sku).first()
            if existing is not None:
                for _k, _v in defaults.items():
                    setattr(existing, _k, _v)
                if existing.is_deleted:
                    existing.is_deleted = False
                    existing.deleted_at = None
                existing.save()
                obj, was_created = existing, False
                updated += 1
            else:
                obj = Product.objects.create(organisation=org, sku=sku, **defaults)
                was_created = True
                created += 1

            # Warehouse + opening stock
            if product_type == "physical":
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
# AI Column Mapping suggestion
# ---------------------------------------------------------------------------

class SuggestColumnMappingView(APIView):
    """
    POST /api/v1/import/suggest-mapping/
    Body: { "entity": "products", "headers": ["Product Name", "Retail Price", ...] }
    Returns: { "mapping": { "name": "Product Name", "selling_price": "Retail Price" } }

    Uses rule-based alias lookup first, then Groq for any remaining headers.
    Works without GROQ_API_KEY — falls back to rules-only.
    """
    permission_classes = [IsAuthenticated, IsVerified]

    def post(self, request):
        from django.conf import settings

        org = _get_or_resolve_org(request)
        if not org:
            return Response({"error": "Organisation not found"}, status=400)

        entity = (request.data.get("entity") or "products").lower()
        headers = request.data.get("headers") or []

        if not headers:
            return Response({"mapping": {}, "method": "none"})

        if entity == "products":
            aliases = PRODUCT_ALIASES
            target_fields = PRODUCT_ALL
        else:
            # customers and accounts keep their required fields; no AI mapping needed
            return Response({"mapping": {}, "method": "none"})

        # Step 1: rule-based matching
        rule_mapping = _rule_based_mapping(headers, aliases)
        # rule_mapping: { our_field → original_csv_header }

        # Step 2: Groq for any remaining unmapped headers + unassigned fields
        used_csv_cols = set(rule_mapping.values())
        api_key = getattr(settings, "GROQ_API_KEY", "") or ""
        ai_mapping = {}
        if api_key:
            ai_mapping = _groq_mapping(headers, target_fields, used_csv_cols, api_key)

        # Merge: rule-based takes priority, AI fills gaps
        combined = {**ai_mapping, **rule_mapping}

        return Response({
            "mapping": combined,  # { our_canonical_field: original_csv_header }
            "method": "ai+rules" if ai_mapping else "rules",
        })


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

        ok, used = _check_import_quota(org, len(rows))
        if not ok:
            return Response(
                {"error": f"Daily import quota exceeded ({DAILY_IMPORT_ROW_QUOTA:,} rows/day, {used:,} already used today). Try again tomorrow."},
                status=429,
            )

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

        ok, used = _check_import_quota(org, len(rows))
        if not ok:
            return Response(
                {"error": f"Daily import quota exceeded ({DAILY_IMPORT_ROW_QUOTA:,} rows/day, {used:,} already used today). Try again tomorrow."},
                status=429,
            )

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
            padded = row + [""] * (len(columns) - len(row))
            writer.writerow(padded[:len(columns)])

        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{entity}_import_template.csv"'
        return response

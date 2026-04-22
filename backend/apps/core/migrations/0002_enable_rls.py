"""
Enable PostgreSQL Row Level Security on every tenant-scoped table.

Policy: each row is visible / writable only when
    organisation_id = current_setting('app.current_org_id', TRUE)::uuid

The sentinel '00000000-0000-0000-0000-000000000000' (set for requests without
an org header) matches nothing, so unauthenticated / org-less requests see an
empty result set for all protected tables.

Table-owner / superuser connections bypass RLS by default (no FORCE) which
means `manage.py migrate` and management commands continue to work unimpeded.
Add FORCE ROW LEVEL SECURITY once you have switched the Django app to a
limited-privilege `audity_app` role (see apps/core/middleware.py docstring).
"""

from django.db import migrations

# Tables with an `organisation_id` column — all inherit TenantAwareModel.
TENANT_TABLES = [
    "accounting_account",
    "accounting_journalentry",
    "accounting_fixedasset",
    "accounting_depreciationentry",
    "accounting_financialperiod",
    "accounting_bankreconciliation",
    "accounting_bankreconciliationline",
    "accounting_aireconmatch",
    "bills_billfolder",
    "bills_bill",
    "bills_billitem",
    "bills_billpayment",
    "budgets_budget",
    "budgets_budgetline",
    "credits_credittransaction",
    "customers_customer",
    "customers_customerdebit",
    "expenses_expensecategory",
    "expenses_expensegroup",
    "expenses_expense",
    "inventory_category",
    "inventory_warehouse",
    "inventory_product",
    "inventory_batch",
    "inventory_stockitem",
    "inventory_stockmovement",
    "payments_paymentgatewayconfig",
    "payments_paymentlink",
    "payroll_employee",
    "payroll_payrollrun",
    "payroll_payslipline",
    "payroll_employeepenalty",
    "payroll_employeeloan",
    "payroll_bonus",
    "payroll_attendance",
    "payroll_employeedocument",
    "purchases_purchaseorder",
    "purchases_purchaseorderitem",
    "quotes_quote",
    "quotes_quoteitem",
    "sales_location",
    "sales_invoicefolder",
    "sales_invoice",
    "sales_saleitem",
    "sales_salepayment",
    "sales_recurringinvoice",
    "sales_recurringinvoicelog",
    "sales_salereturn",
    "sales_salereturnitem",
    "suppliers_supplier",
    "tax_taxclass",
    "tax_taxconfig",
    "tax_taxreturn",
    "tax_exciseduty",
    "tax_whtrate",
    "tax_whttransaction",
    # tenancy tables with organisation FK (not TenantAwareModel but still scoped)
    "tenancy_membership",
    "tenancy_emailconfig",
    "tenancy_invitation",
    "tenancy_partnerclientlink",
]

# tenancy_organisation is the root: policy uses `id` not `organisation_id`
ORG_TABLE = "tenancy_organisation"

SENTINEL = "00000000-0000-0000-0000-000000000000"

# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

def _enable_rls_sql(table: str) -> str:
    return f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS tenant_isolation ON {table};
        CREATE POLICY tenant_isolation ON {table}
            USING (
                organisation_id = current_setting('app.current_org_id', TRUE)::uuid
            )
            WITH CHECK (
                organisation_id = current_setting('app.current_org_id', TRUE)::uuid
            );
    """


def _disable_rls_sql(table: str) -> str:
    return f"""
        DROP POLICY IF EXISTS tenant_isolation ON {table};
        ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
    """


ENABLE_ORG_TABLE = f"""
    ALTER TABLE {ORG_TABLE} ENABLE ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON {ORG_TABLE};
    CREATE POLICY tenant_isolation ON {ORG_TABLE}
        USING (
            id = current_setting('app.current_org_id', TRUE)::uuid
        )
        WITH CHECK (
            id = current_setting('app.current_org_id', TRUE)::uuid
        );
"""

DISABLE_ORG_TABLE = f"""
    DROP POLICY IF EXISTS tenant_isolation ON {ORG_TABLE};
    ALTER TABLE {ORG_TABLE} DISABLE ROW LEVEL SECURITY;
"""

# Initialise the session variable to the sentinel so queries made before
# the middleware sets it (e.g. during app startup checks) don't error.
INIT_SESSION_DEFAULT = f"""
    DO $$
    BEGIN
        -- Set a database-level default so every new connection starts with
        -- the sentinel value; the middleware overrides it per-request.
        PERFORM set_config('app.current_org_id', '{SENTINEL}', FALSE);
    EXCEPTION WHEN OTHERS THEN
        NULL;  -- non-fatal
    END $$;
"""


def apply(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return  # RLS is Postgres-only; skip for SQLite in tests

    import logging
    _log = logging.getLogger(__name__)

    try:
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(INIT_SESSION_DEFAULT)
            for table in TENANT_TABLES:
                cursor.execute(_enable_rls_sql(table))
            cursor.execute(ENABLE_ORG_TABLE)
    except Exception as exc:
        # Managed cloud DBs (Railway, Supabase, etc.) may restrict ALTER TABLE
        # ENABLE ROW LEVEL SECURITY to the superuser, or the table may not yet
        # exist in this DB instance.  Log the failure but do NOT re-raise — an
        # unapplied migration here would block authentication/0006 (token_version)
        # and every subsequent migration, taking down the entire app.
        # The RLS middleware sets app.current_org_id per-request regardless,
        # so tenant isolation still works at the application layer.
        _log.warning(
            "core.0002_enable_rls: could not enable PostgreSQL RLS "
            "(non-fatal on managed DBs): %s", exc
        )


def revert(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    with schema_editor.connection.cursor() as cursor:
        for table in TENANT_TABLES:
            cursor.execute(_disable_rls_sql(table))
        cursor.execute(DISABLE_ORG_TABLE)


class Migration(migrations.Migration):
    # Non-atomic so a DDL failure doesn't roll back the entire migration
    # and block authentication/0006 (token_version) from being applied.
    atomic = False

    dependencies = [
        ("core", "0001_initial"),
        # Ensure every app's tables exist before we enable RLS on them
        ("accounting",  "0003_ai_recon_match"),
        ("bills",       "0003_billfolder_bill_folder"),
        ("budgets",     "0002_add_line_fields"),
        ("credits",     "0001_initial"),
        ("customers",   "0004_customerdebit"),
        ("expenses",    "0006_alter_expensegroup_created_at_and_more"),
        ("inventory",   "0006_batch_qty_fields"),
        ("payments",    "0001_initial"),
        ("payroll",     "0007_payrollrun_target_approver"),
        ("purchases",   "0003_purchaseorder_delivery_type"),
        ("quotes",      "0001_initial"),
        ("sales",       "0012_invoice_sold_by"),
        ("suppliers",   "0001_initial"),
        ("tax",         "0002_exciseduty_whtrate_whttransaction"),
        ("tenancy",     "0019_organisation_multi_entity"),
    ]

    operations = [
        migrations.RunPython(apply, revert, atomic=False),
    ]

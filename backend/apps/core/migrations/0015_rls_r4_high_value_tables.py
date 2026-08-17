"""
R-4 — enable RLS on 42 high-value tenant tables.

Payroll, payments, tax, fixed-asset support tables and subscription billing —
the ones where a wrong policy is not an inconvenience but a payroll run that
sees no employees or a tax screen that shows nothing owed.

Deliberately last, and only after R-2 and R-3 have proven the policy shape
against real code paths.

tenancy_partneraccessrequest is the one to watch here: partner flows can run
before a client org is selected, so the R-4 rehearsal must confirm the partner
access-request screen still loads. tenancy_membership and tenancy_organisation
remain excluded — RLS on those broke login once already (migrations 0006-0008).

Policy shape, the FORCE decision, savepoint handling and the deliberate
exclusions (tenancy_membership / tenancy_organisation / core_auditlog /
accounting_journalline) are all documented in apps/core/rls_policy.py and
migration 0013. This batch reuses those helpers so the policy applied here is
byte-identical to every other batch.
"""

from django.db import migrations

from apps.core.rls_policy import apply_rls, revert_rls

TABLES = [
    "accounting_accountmapping",
    "accounting_accountsubtype",
    "accounting_assetrevaluation",
    "accounting_assettransfer",
    "accounting_assettype",
    "accounting_fiscalyear",
    "accounting_periodpostinggrant",
    "payments_banktransferclaim",
    "payments_merchantbankaccount",
    "payments_paymenteventlog",
    "payments_settlementbatch",
    "payments_settlementline",
    "payments_virtualaccount",
    "payroll_advancepolicy",
    "payroll_advancerequest",
    "payroll_benefitplan",
    "payroll_clearancechecklistitem",
    "payroll_compensationrecord",
    "payroll_employeebenefit",
    "payroll_employeetaxprofile",
    "payroll_exitinterview",
    "payroll_leavebalance",
    "payroll_leaverequest",
    "payroll_leavetype",
    "payroll_offboardingcase",
    "payroll_offboardingchecklisttemplate",
    "payroll_payrolladjustment",
    "payroll_payrollsettings",
    "payroll_payslipdelivery",
    "payroll_publicholiday",
    "payroll_statutoryremittance",
    "payroll_taxauthority",
    "subscriptions_organisationintegrationentitlement",
    "subscriptions_paymenthistory",
    "tax_capitalallowanceclaim",
    "tax_caratetable",
    "tax_deferredtaxitem",
    "tax_relatedpartytransaction",
    "tax_taxobligation",
    "tax_vattransaction",
    "tax_whtcertificate",
    "tenancy_partneraccessrequest",
]

LABEL = "core.0015 (R-4)"


class Migration(migrations.Migration):
    atomic = False


    # Every app whose tables this batch touches must have created them first.
    # Without these, Django is free to run this migration before those apps'
    # initial migrations: ALTER TABLE then fails on a table that does not exist
    # yet, the per-table handler logs a warning and continues, and the migration
    # is recorded as applied having protected nothing. That is exactly how
    # migrations 0006/0007 came to be silently no-ops. Verified: 8/68 tables
    # were enabled before these dependencies were added, 68/68 after.
    dependencies = [
        ("core", "0014_rls_r3_operational_tables"),
        ("accounting", "0020_backfill_control_account_flags"),
        ("payments", "0003_settlementbatch_settlementline"),
        ("payroll", "0017_employeeloan_approved_at_employeeloan_approved_by_and_more"),
        ("subscriptions", "0023_integrationproduct_paymenthistory_expected_amount_and_more"),
        ("tax", "0008_capitalallowanceclaim_asset_and_more"),
        ("tenancy", "0036_membership_granted_scope"),
    ]

    operations = [
        migrations.RunPython(apply_rls(TABLES, LABEL), revert_rls(TABLES, LABEL), atomic=False),
    ]

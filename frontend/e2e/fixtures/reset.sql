-- Reset the mutable fixtures the browser suites write to.
--
-- Several specs mutate the data they assert on, so they pass once against a
-- freshly seeded database and fail on every run afterwards. That is not a
-- product defect and chasing it as one wastes a lot of time — the symptoms look
-- exactly like regressions:
--
--   payments  INV-00001 is collected and confirmed, so it becomes `paid`.
--             "Ask customer to pay" then correctly disappears and the collect
--             tests can never open the modal again.
--   today     the messaging spec creates a conversation, so "No messages yet —
--             say hello." is no longer on screen for the next run; the leave
--             spec books days, so the accrued balance is already spent and a
--             request that should fit now trips the overbooking warning.
--   today     the integrations purchase spec writes a PENDING entitlement
--             before calling Paystack, so the card flips to "Restore access"
--             and no longer offers a Purchase button.
--
-- Run this immediately BEFORE a suite, not after: a run that fails partway
-- still leaves state behind, so cleaning up afterwards is not reliable.
--
--   docker exec finventory-db-1 psql -U finv_app -d finventory_uitest \
--     -f /dev/stdin < frontend/e2e/fixtures/reset.sql
--
-- The durable fix is for each spec to provision and tear down its own data.
-- Until then this keeps the suites repeatable.

BEGIN;

-- ── messaging ───────────────────────────────────────────────────────────────
DELETE FROM messaging_messageattachment;
DELETE FROM messaging_message;
DELETE FROM messaging_conversationparticipant;
DELETE FROM messaging_conversation;

-- ── leave ───────────────────────────────────────────────────────────────────
DELETE FROM payroll_leaverequest;
UPDATE payroll_leavebalance SET taken_days = 0, pending_days = 0;

-- ── integrations marketplace ────────────────────────────────────────────────
-- PaymentHistory holds the entitlement with on_delete=PROTECT, deliberately: a
-- payment is a financial fact and must never be silently orphaned. The test
-- payment therefore has to go first.
DELETE FROM subscriptions_paymenthistory
 WHERE integration_entitlement_id IN (
   SELECT e.id
     FROM subscriptions_organisationintegrationentitlement e
     JOIN subscriptions_integrationproduct p ON p.id = e.product_id
    WHERE p.key = 'quickbooks'
 );
DELETE FROM subscriptions_organisationintegrationentitlement
 WHERE product_id = (SELECT id FROM subscriptions_integrationproduct WHERE key = 'quickbooks');

-- ── payments: restore the fixture invoice to collectible ────────────────────
DELETE FROM payments_banktransferclaim
 WHERE invoice_id = (SELECT id FROM sales_invoice WHERE invoice_number = 'INV-00001');
DELETE FROM payments_virtualaccount
 WHERE invoice_id = (SELECT id FROM sales_invoice WHERE invoice_number = 'INV-00001');
DELETE FROM payments_paymentlink
 WHERE invoice_id = (SELECT id FROM sales_invoice WHERE invoice_number = 'INV-00001');
DELETE FROM sales_salepayment
 WHERE invoice_id = (SELECT id FROM sales_invoice WHERE invoice_number = 'INV-00001');
UPDATE sales_invoice
   SET status = 'confirmed', amount_paid = 0, amount_due = total_amount
 WHERE invoice_number = 'INV-00001';

COMMIT;

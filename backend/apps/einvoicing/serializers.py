"""
DRF serializers for the FIRS e-invoicing app.

Used in Phase 6 ViewSets, Phase 7 sandbox views, and the Phase 3 webhook view.

FirsConfigSerializer           — Read/update org-level DigiTax credentials.
                                  app_api_key is write-only (EncryptedCharField).
FirsSubmissionSerializer       — Read-only audit log view.
                                  Handles nullable invoice (is_sandbox_test rows).
FirsSubmissionDetailSerializer — Extended with payload_json / response_raw.
SandboxTestRunSerializer       — Phase 7: batch run records.
WebhookPayloadSerializer       — Validates the incoming DigiTax webhook body.
"""

from rest_framework import serializers

from apps.einvoicing.models import FirsConfig, FirsSubmission, SandboxTestRun


class FirsConfigSerializer(serializers.ModelSerializer):
    """
    Serializer for FirsConfig — org-level DigiTax credentials and enrollment status.

    app_api_key is declared write_only so the encrypted value is never returned
    in API responses. A separate 'has_api_key' read-only field lets the UI show
    whether a key is set without exposing the key itself.
    """

    # Show whether a key exists without exposing the value
    has_api_key = serializers.SerializerMethodField(
        help_text="True if an API key has been stored (write-only field)."
    )

    class Meta:
        model = FirsConfig
        fields = [
            "id",
            "organisation",
            "is_enrolled",
            "tin",
            "business_name",
            "app_api_key",      # write-only
            "has_api_key",      # read-only derived
            "app_base_url",
            "use_sandbox",
            "digitax_party_id",
            "enrolled_at",
            "last_test_at",
            "last_test_ok",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id", "organisation", "digitax_party_id",
            "enrolled_at", "last_test_at", "last_test_ok",
            "created_at", "updated_at",
        ]
        extra_kwargs = {
            # Never return the encrypted API key in responses
            "app_api_key": {"write_only": True, "required": False, "allow_blank": True},
        }

    def get_has_api_key(self, obj) -> bool:
        """Return True if an API key has been stored."""
        return bool(obj.app_api_key)


class FirsSubmissionSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for FirsSubmission — audit log of submission attempts.

    Handles nullable invoice: sandbox test rows (is_sandbox_test=True) have
    invoice=None; invoice_number and customer_name fall back gracefully.

    payload_json is excluded from list view (can be large); use detail endpoint.
    """

    # Use SerializerMethodField so nullable invoice doesn't raise AttributeError
    invoice_number = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()

    class Meta:
        model = FirsSubmission
        fields = [
            "id",
            "invoice",
            "invoice_number",
            "customer_name",
            "submission_ref",
            "transaction_type",
            "submission_kind",
            "is_sandbox_test",
            "status",
            "irn",
            "csid",
            "attempt_count",
            "error_detail",
            "submitted_at",
            "cleared_at",
            "last_attempted_at",
            "created_at",
        ]
        read_only_fields = fields  # entire serializer is read-only

    def get_invoice_number(self, obj) -> str:
        """Return the invoice number, or empty string for sandbox test rows."""
        try:
            return obj.invoice.invoice_number if obj.invoice else ""
        except Exception:
            return ""

    def get_customer_name(self, obj) -> str:
        """Return the customer name, or 'Sandbox Test' for sandbox test rows."""
        if obj.is_sandbox_test:
            return "Sandbox Test"
        try:
            return obj.invoice.customer.name if obj.invoice and obj.invoice.customer else "Walk-in"
        except Exception:
            return ""


class FirsSubmissionDetailSerializer(FirsSubmissionSerializer):
    """
    Extended version with payload_json and response_raw — detail endpoint only.
    Payload may be large; only fetch when explicitly requested.
    """

    class Meta(FirsSubmissionSerializer.Meta):
        fields = FirsSubmissionSerializer.Meta.fields + ["payload_json", "response_raw"]


class SandboxTestRunSerializer(serializers.ModelSerializer):
    """
    Read-only serializer for SandboxTestRun batch records.
    Used in the sandbox progress response.
    """

    class Meta:
        model = SandboxTestRun
        fields = [
            "id",
            "mode",
            "outcome",
            "target_count",
            "completed_count",
            "error_detail",
            "started_at",
            "finished_at",
            "created_at",
        ]
        read_only_fields = fields


class WebhookPayloadSerializer(serializers.Serializer):
    """
    Validates the JSON body of a DigiTax IRN webhook POST.

    DigiTax sends a payload like:
        {
            "submission_ref": "abc123",
            "irn":            "2013528595NNVPE-E3A89069-20260515",
            "csid":           "CSID-...",
            "invoice_number": "FIRS-INV-0001",
            "qr_code":        "<base64 PNG>" (optional),
            "status":         "CLEARED"
        }

    All fields except qr_code are required. Unknown extra fields are silently
    ignored (DigiTax may add fields in future API versions).
    """

    submission_ref  = serializers.CharField(max_length=200)
    irn             = serializers.CharField(max_length=200)
    csid            = serializers.CharField(max_length=500, required=False, default="", allow_blank=True)
    invoice_number  = serializers.CharField(
        max_length=200,
        required=False,
        default="",
        allow_blank=True,
        help_text="FIRS-assigned invoice number (not Audity's trader_invoice_number).",
    )
    qr_code         = serializers.CharField(
        required=False,
        default="",
        allow_blank=True,
        help_text="Base64-encoded QR code PNG (optional — Audity generates one if absent).",
    )
    status          = serializers.CharField(
        max_length=50,
        required=False,
        default="CLEARED",
        allow_blank=True,
        help_text="DigiTax clearance status; expected 'CLEARED' for success callbacks.",
    )

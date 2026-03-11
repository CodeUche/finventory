"""
Shared validators for DRF serializers.

Usage in a serializer field:
    from apps.core.validators import validate_image_upload, validate_file_upload

    logo = serializers.ImageField(validators=[validate_image_upload])
    attachment = serializers.FileField(validators=[validate_file_upload])

Or via extra_kwargs in Meta:
    extra_kwargs = {"logo": {"validators": [validate_image_upload]}}
"""

import os

from django.core.exceptions import ValidationError

# ── File type allowlists ───────────────────────────────────────────────────────
# Keep these conservative — only accept formats the UI actually uses.

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}
_IMAGE_MIME_PREFIX = ("image/",)

_DOCUMENT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
_DOCUMENT_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/jpg"}

# Letterhead allows images AND office/PDF documents
_LETTERHEAD_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".pdf", ".doc", ".docx"}

# Hard upper bounds — settings.DATA_UPLOAD_MAX_MEMORY_SIZE is the global cap,
# but per-field limits give a tighter, more informative error message.
_MAX_IMAGE_BYTES = 5 * 1024 * 1024    # 5 MB
_MAX_DOCUMENT_BYTES = 10 * 1024 * 1024  # 10 MB


def validate_image_upload(value):
    """
    Validate that an uploaded file is an acceptable image.

    Checks:
      1. File extension is in the image allowlist.
      2. File size does not exceed 5 MB.

    Used on: Organisation.logo, Organisation.letterhead, User.avatar
    """
    ext = os.path.splitext(value.name)[1].lower()
    if ext not in _IMAGE_EXTENSIONS:
        raise ValidationError(
            f"Unsupported image format '{ext}'. "
            f"Allowed: {', '.join(sorted(_IMAGE_EXTENSIONS))}"
        )
    if hasattr(value, "size") and value.size > _MAX_IMAGE_BYTES:
        raise ValidationError(
            f"Image file too large ({value.size // 1024} KB). Maximum allowed: 5 MB."
        )


def validate_file_upload(value):
    """
    Validate that an uploaded file is an acceptable document (PDF or image).

    Checks:
      1. File extension is in the document allowlist.
      2. File size does not exceed 10 MB.

    Used on: PurchaseOrder.receipt, Expense.attachment, Bill.attachment
    """
    ext = os.path.splitext(value.name)[1].lower()
    if ext not in _DOCUMENT_EXTENSIONS:
        raise ValidationError(
            f"Unsupported file format '{ext}'. "
            f"Allowed: {', '.join(sorted(_DOCUMENT_EXTENSIONS))}"
        )
    if hasattr(value, "size") and value.size > _MAX_DOCUMENT_BYTES:
        raise ValidationError(
            f"File too large ({value.size // 1024} KB). Maximum allowed: 10 MB."
        )


def validate_letterhead_upload(value):
    """
    Validate that an uploaded letterhead file is an acceptable image or document.

    Checks:
      1. File extension is in the letterhead allowlist (images + PDF/DOC/DOCX).
      2. File size does not exceed 10 MB.

    Used on: Organisation.letterhead
    """
    ext = os.path.splitext(value.name)[1].lower()
    if ext not in _LETTERHEAD_EXTENSIONS:
        raise ValidationError(
            f"Unsupported letterhead format '{ext}'. "
            f"Allowed: {', '.join(sorted(_LETTERHEAD_EXTENSIONS))}"
        )
    if hasattr(value, "size") and value.size > _MAX_DOCUMENT_BYTES:
        raise ValidationError(
            f"Letterhead file too large ({value.size // 1024} KB). Maximum allowed: 10 MB."
        )

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

import filetype
from django.core.exceptions import ValidationError

# ── File type allowlists ───────────────────────────────────────────────────────
# Keep these conservative — only accept formats the UI actually uses.

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
_IMAGE_MIME_PREFIX = ("image/",)

_DOCUMENT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
_DOCUMENT_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/jpg"}

# Letterhead allows images AND PDF — SVG excluded (can carry embedded JS)
_LETTERHEAD_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf"}
_LETTERHEAD_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/gif", "image/webp", "image/jpg"}

# Hard upper bounds — settings.DATA_UPLOAD_MAX_MEMORY_SIZE is the global cap,
# but per-field limits give a tighter, more informative error message.
_MAX_IMAGE_BYTES = 5 * 1024 * 1024    # 5 MB
_MAX_DOCUMENT_BYTES = 10 * 1024 * 1024  # 10 MB


def sniff_image_bytes(data: bytes) -> str | None:
    """
    Return the detected MIME type of raw image bytes, or None if not a known image.
    Uses magic bytes (not Content-Type header) — spoofing-resistant.
    """
    kind = filetype.guess(data)
    if kind and kind.mime.startswith("image/"):
        return kind.mime
    return None


def validate_image_upload(value):
    """
    Validate that an uploaded file is an acceptable image.

    Checks:
      1. File extension is in the image allowlist.
      2. Magic bytes confirm it is actually an image (not a spoofed extension).
      3. File size does not exceed 5 MB.

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
    # Magic byte check — read first 261 bytes (enough for filetype detection)
    try:
        header = value.read(261)
        value.seek(0)
        if header and sniff_image_bytes(header) is None:
            raise ValidationError(
                "File content does not match an image format. "
                "Please upload a real PNG, JPEG, WebP, or GIF file."
            )
    except (AttributeError, OSError):
        pass  # Stream not seekable — skip sniffing, extension check is enough


def validate_file_upload(value):
    """
    Validate that an uploaded file is an acceptable document (PDF or image).

    Checks:
      1. File extension is in the document allowlist.
      2. Magic bytes confirm the file type matches its extension.
      3. File size does not exceed 10 MB.

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
    # Magic byte check
    try:
        header = value.read(261)
        value.seek(0)
        if header:
            kind = filetype.guess(header)
            if kind is None or kind.mime not in _DOCUMENT_MIME_TYPES:
                raise ValidationError(
                    "File content does not match an allowed format (PDF or image). "
                    "Please upload a real PDF, PNG, or JPEG file."
                )
    except (AttributeError, OSError):
        pass


def validate_letterhead_upload(value):
    """
    Validate that an uploaded letterhead file is an acceptable image or PDF.

    Checks:
      1. File extension is in the letterhead allowlist (images + PDF; SVG excluded).
      2. Magic bytes confirm the file type is genuine.
      3. File size does not exceed 10 MB.

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
    # Magic byte check — prevents disguised executables or SVG-with-JS
    try:
        header = value.read(261)
        value.seek(0)
        if header:
            kind = filetype.guess(header)
            if kind is None or kind.mime not in _LETTERHEAD_MIME_TYPES:
                raise ValidationError(
                    "File content does not match an allowed format (PDF or image). "
                    "Please upload a real PDF, PNG, JPEG, GIF, or WebP file."
                )
    except (AttributeError, OSError):
        pass

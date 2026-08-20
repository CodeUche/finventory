"""Turn a duplicate-key collision into a 400 the user can act on.

Most tenant models are unique on a natural key scoped to the organisation —
(organisation, sku), (organisation, code), (organisation, name). The
organisation half is set by the view, never sent by the client, so it is not a
serializer field; DRF therefore cannot build a UniqueTogetherValidator for it
and never checks the pair. A duplicate SKU sailed through validation, hit the
database, and came back as an unhandled IntegrityError — a 500, for a routine
typo, which also buries a real outage in noise when someone is scanning error
rates.

A few viewsets already wrapped create() by hand to catch this (Warehouse being
the clearest). This is that same handling, in one place, so it is consistent
and cannot be forgotten on the next model.

Deliberately narrow: only a UNIQUE violation is converted. Any other
IntegrityError — a foreign key, a NOT NULL — is re-raised untouched, because
those are bugs and should stay loud.
"""
from django.db import IntegrityError, transaction
from rest_framework.response import Response


def is_unique_violation(exc: Exception) -> bool:
    """True for a unique-constraint violation, on PostgreSQL or SQLite."""
    pgcode = getattr(getattr(exc, "__cause__", None), "pgcode", None)
    if pgcode == "23505":  # postgres unique_violation
        return True
    text = str(exc).lower()
    return "unique constraint" in text or "duplicate key" in text


class FriendlyUniqueErrorMixin:
    """Answer 400 instead of 500 when a create/update collides on a unique key.

    Set ``unique_error_message`` on the viewset to say which field it was —
    "already exists" is only useful if the user can tell what to change.
    """

    unique_error_message = "A record with those details already exists."

    def _guard(self, call):
        # atomic() so the failed statement is rolled back cleanly: without it the
        # connection stays poisoned and the next query in the request raises
        # TransactionManagementError instead of the friendly response below.
        try:
            with transaction.atomic():
                return call()
        except IntegrityError as exc:
            if not is_unique_violation(exc):
                raise
            return Response({"error": self.unique_error_message}, status=400)

    def create(self, request, *args, **kwargs):
        return self._guard(lambda: super(FriendlyUniqueErrorMixin, self).create(request, *args, **kwargs))

    def update(self, request, *args, **kwargs):
        return self._guard(lambda: super(FriendlyUniqueErrorMixin, self).update(request, *args, **kwargs))

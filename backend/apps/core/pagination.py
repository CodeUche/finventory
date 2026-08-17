"""
Custom pagination classes.

Standardised pagination envelope keeps client code simple and
prevents unbounded query results (DoS protection).
"""

from django.db.models import QuerySet
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


def ensure_stable_ordering(queryset):
    """
    Give a queryset an order the database cannot change between requests
    (finding NEW-16).

    Paging with LIMIT/OFFSET only means anything if the rows come back in the
    same order every time. Two cases break that, and every tenant model in this
    application was in one of them:

      * No ordering at all. Postgres may return rows however it likes and is
        not obliged to choose the same way twice.
      * An ordering whose last key is not unique, e.g. ``-created_at``. Rows
        that tie can swap places between two requests — and ties are normal,
        since invoices raised in one batch share a timestamp.

    Either way page 2 is not guaranteed to continue where page 1 stopped: a row
    can appear on both pages, and another on neither. Appending the primary key
    removes the ambiguity, because no two rows share one.

    This runs at the paginator rather than on 134 model ``Meta`` classes for
    two reasons. It covers endpoints that build a queryset by hand, which model
    ordering would miss. And it touches only paginated list responses — nested
    reads like ``invoice.items.all()`` keep the order they have now, so line
    items on a document are not silently reversed.

    Where there is no ordering to extend, ``created_at`` ascending is used. That
    is close to what these endpoints already return, since an unordered scan
    tends to come back in insertion order. The aim here is to make today's
    apparent order reliable, not to choose a new one — several screens would
    likely read better newest-first, but that is a product decision and not
    this fix.
    """
    if not isinstance(queryset, QuerySet):
        return queryset  # some views paginate plain lists

    query = queryset.query

    # Leave alone anything where appending a column changes the result rather
    # than just the order:
    #   values()/aggregate -> pk would join the GROUP BY and split the buckets
    #   DISTINCT ON        -> Postgres requires ORDER BY to start with those
    #   union/intersection -> cannot be ordered by an arbitrary column
    if query.values_select or query.group_by or query.distinct_fields or query.combinator:
        return queryset

    ordering = list(query.order_by) or list(queryset.model._meta.ordering or [])

    if ordering:
        last = ordering[-1]
        name = last.lstrip("-")
        if name in ("pk", "id"):
            return queryset
        try:
            if queryset.model._meta.get_field(name).unique:
                return queryset  # already unambiguous
        except Exception:
            return queryset  # related lookup or expression — do not second-guess it
        tiebreak = "-pk" if last.startswith("-") else "pk"
        return queryset.order_by(*ordering, tiebreak)

    field_names = {f.name for f in queryset.model._meta.fields}
    if "created_at" in field_names:
        return queryset.order_by("created_at", "pk")
    return queryset.order_by("pk")


class StableOrderingMixin:
    """Applies ensure_stable_ordering to every page this paginator serves."""

    def paginate_queryset(self, queryset, request, view=None):
        return super().paginate_queryset(
            ensure_stable_ordering(queryset), request, view
        )


class StandardResultsSetPagination(StableOrderingMixin, PageNumberPagination):
    """Default: 25 items per page, max 5000 (for full client-side pagination)."""

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 5000

    def get_paginated_response(self, data):
        return Response(
            {
                "count": self.page.paginator.count,
                "total_pages": self.page.paginator.num_pages,
                "current_page": self.page.number,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "results": data,
            }
        )

    def get_paginated_response_schema(self, schema):
        return {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "example": 123},
                "total_pages": {"type": "integer", "example": 5},
                "current_page": {"type": "integer", "example": 1},
                "next": {"type": "string", "nullable": True},
                "previous": {"type": "string", "nullable": True},
                "results": schema,
            },
        }


class LargeResultsSetPagination(StableOrderingMixin, PageNumberPagination):
    """For report endpoints that need more rows per page."""

    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 1000

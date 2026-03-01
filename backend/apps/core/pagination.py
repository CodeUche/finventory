"""
Custom pagination classes.

Standardised pagination envelope keeps client code simple and
prevents unbounded query results (DoS protection).
"""

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class StandardResultsSetPagination(PageNumberPagination):
    """Default: 25 items per page, max 200."""

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 200

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


class LargeResultsSetPagination(PageNumberPagination):
    """For report endpoints that need more rows per page."""

    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 1000

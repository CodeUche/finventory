"""
WhiteLabelMiddleware — detects custom-domain requests and attaches branding config.

Runs before authentication. Sets request.white_label to the WhiteLabelConfig
instance for the matched domain, or None for the main Audity domain.
Zero cost for non-white-label traffic (unique index + IS NULL guard).
"""
import logging

logger = logging.getLogger(__name__)


class WhiteLabelMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.white_label = self._resolve(request)
        return self.get_response(request)

    @staticmethod
    def _resolve(request):
        host = request.META.get("HTTP_HOST", "").split(":")[0].lower().strip()
        if not host:
            return None
        try:
            from .models import WhiteLabelConfig
            return WhiteLabelConfig.objects.select_related("partner_profile").get(
                custom_domain=host,
                is_domain_verified=True,
                ssl_active=True,
            )
        except WhiteLabelConfig.DoesNotExist:
            return None
        except Exception as e:
            logger.debug("WhiteLabelMiddleware: lookup failed for host %s: %s", host, e)
            return None

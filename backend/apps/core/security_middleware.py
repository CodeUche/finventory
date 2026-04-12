"""
Security headers middleware.

Injects hardened HTTP security headers on every response.
These complement Django's built-in SecurityMiddleware and cover
headers that Django does not set by default (CSP, Permissions-Policy).
"""


class SecurityHeadersMiddleware:
    """
    Adds security headers that Django's SecurityMiddleware does not handle:

    - Content-Security-Policy: restricts which resources the browser loads
    - Permissions-Policy: disables browser features the app doesn't need
    - Cross-Origin-Opener-Policy: isolates browsing context from popups
    - Cross-Origin-Resource-Policy: controls cross-origin resource reads
    """

    # API responses are JSON — no scripts, styles, or frames needed.
    # Adjust if you ever serve HTML from the Django backend (e.g. email verify page).
    CSP = (
        "default-src 'none'; "
        "script-src 'none'; "
        "style-src 'none'; "
        "img-src 'none'; "
        "font-src 'none'; "
        "connect-src 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'none'; "
        "base-uri 'none';"
    )

    # Relax CSP only for the HTML email-verification page
    CSP_HTML = (
        "default-src 'none'; "
        "style-src 'unsafe-inline'; "
        "img-src 'self' data:; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "base-uri 'self';"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        content_type = response.get("Content-Type", "")
        if "text/html" in content_type:
            response["Content-Security-Policy"] = self.CSP_HTML
        else:
            response["Content-Security-Policy"] = self.CSP

        response["Permissions-Policy"] = (
            "geolocation=(), microphone=(), camera=(), payment=(), "
            "usb=(), magnetometer=(), accelerometer=(), gyroscope=()"
        )
        response["Cross-Origin-Opener-Policy"] = "same-origin"
        response["Cross-Origin-Resource-Policy"] = "same-origin"
        response["Cross-Origin-Embedder-Policy"] = "require-corp"

        # Remove headers that leak server information
        response.headers.pop("Server", None)
        response.headers.pop("X-Powered-By", None)

        return response

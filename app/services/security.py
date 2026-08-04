from __future__ import annotations

from starlette.requests import Request
from starlette.responses import Response


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def is_cross_site_unsafe_request(request: Request) -> bool:
    """Reject browser-declared cross-site writes without breaking API tests.

    Modern browsers send Sec-Fetch-Site. Same-origin and same-site writes are
    accepted; explicitly cross-site unsafe methods are blocked. Requests from
    non-browser clients that omit the header continue through normal auth and
    permission checks.
    """
    if request.method.upper() in SAFE_METHODS:
        return False
    return request.headers.get("sec-fetch-site", "").casefold() == "cross-site"


def apply_security_headers(
    response: Response,
    *,
    secure_transport: bool,
    cache_private_content: bool = False,
) -> Response:
    """Apply low-risk browser protections without breaking Bulma or HTMX."""
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), microphone=(), geolocation=()",
    )

    if not cache_private_content:
        response.headers.setdefault(
            "Cache-Control",
            "no-store, max-age=0",
        )

    if secure_transport:
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )

    return response

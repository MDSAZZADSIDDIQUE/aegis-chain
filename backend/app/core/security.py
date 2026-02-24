"""API key authentication dependency for AegisChain endpoints.

Usage
-----
    from app.core.security import verify_api_key
    from fastapi import Depends

    router = APIRouter(dependencies=[Depends(verify_api_key)])

Or per-endpoint::

    @router.get("/protected", dependencies=[Depends(verify_api_key)])

Dev mode
--------
When ``AEGIS_API_KEY`` is empty (the default), the dependency is a no-op so
the local dev server works without any configuration.  Set the variable to a
non-empty string to enable enforcement.

Exempt endpoints
----------------
* ``GET /health``       — infrastructure health probe; no auth required.
* ``POST /slack/actions`` — authenticated via Slack request-signature HMAC;
  uses its own ``verify_slack_signature`` guard instead.
"""

from __future__ import annotations

from fastapi import Header, HTTPException, status

from app.core.config import settings


async def verify_api_key(
    x_aegischain_key: str = Header(default="", alias="X-AegisChain-Key"),
) -> None:
    """FastAPI dependency: validate the ``X-AegisChain-Key`` request header.

    Raises ``HTTP 401`` when the key is set in config and the header is absent
    or does not match.  Passes silently when ``AEGIS_API_KEY`` is not
    configured (dev / test environments).
    """
    if not settings.aegis_api_key:
        # Auth disabled — environment has no key configured.
        return

    if x_aegischain_key != settings.aegis_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-AegisChain-Key header",
            headers={"WWW-Authenticate": "ApiKey"},
        )

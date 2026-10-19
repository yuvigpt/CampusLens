"""
CampusLens - Supabase Auth verification.

A request is trusted only after its bearer JWT has been cryptographically
verified against the project's JWKS, and only then is the role looked up in the
``profiles`` table.

Deliberate design choices:
  * The role is NEVER read from the token. A hand-crafted JWT claiming
    ``role: admin`` therefore grants nothing, because the claim is ignored.
  * The service-role key is never accepted here. Only the project anon key is
    used, for fetching JWKS.
  * Failures produce a generic message; no token text, key or URL is echoed.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import config, database

logger = logging.getLogger("campuslens.auth")

JWKS_TTL_SECONDS = 600
REQUEST_TIMEOUT_SECONDS = 10.0

# Only asymmetric algorithms are accepted. "none" and any symmetric HMAC are
# rejected outright, which blocks the classic algorithm-confusion attack.
#
# ES256 is required, not optional: current Supabase projects sign with ECDSA
# P-256, so the JWKS publishes an ES256 key. Without it every real token is
# rejected at this line, before signature verification ever runs.
ALLOWED_ALGS = {"RS256", "RS384", "RS512", "ES256"}

bearer = HTTPBearer(auto_error=False)

_jwks_cache: dict[str, Any] = {"at": 0.0, "keys": {}}


def _unauthorized(detail: str = "Not authenticated.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def reset_jwks_cache() -> None:
    """Drop the cached signing keys (used by tests)."""
    _jwks_cache["at"] = 0.0
    _jwks_cache["keys"] = {}


def _fetch_jwks(settings: config.Settings) -> dict[str, dict[str, Any]]:
    """Fetch and cache the project's signing keys."""
    now = time.monotonic()
    if now - _jwks_cache["at"] < JWKS_TTL_SECONDS and _jwks_cache["keys"]:
        return _jwks_cache["keys"]

    url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    headers = {"apikey": settings.supabase_anon_key}
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        # Never include the URL, the key or the response body.
        logger.error("jwks fetch failed (%s)", type(exc).__name__)
        raise _unauthorized("Authentication service unavailable.") from None

    keys: dict[str, dict[str, Any]] = {}
    for entry in payload.get("keys", []):
        kid = entry.get("kid")
        if kid:
            keys[kid] = entry

    if not keys:
        logger.error("jwks response contained no usable keys")
        raise _unauthorized("Authentication service unavailable.")

    _jwks_cache["keys"] = keys
    _jwks_cache["at"] = now
    return keys


def verify_token(token: str, settings: config.Settings) -> str:
    """Return the verified `sub` (user id) from a bearer token.

    Raises HTTPException(401) for anything that is not a valid, unexpired token
    signed by this project.
    """
    import jwt

    if not isinstance(token, str) or len(token) > 8192:
        raise _unauthorized("Invalid token.")

    try:
        header = jwt.get_unverified_header(token)
    except Exception:
        raise _unauthorized("Invalid token.") from None

    alg = header.get("alg")
    if alg not in ALLOWED_ALGS:
        logger.warning("rejected token with algorithm %s", alg)
        raise _unauthorized("Invalid token.")

    kid = header.get("kid")
    if not kid:
        raise _unauthorized("Invalid token.")

    keys = _fetch_jwks(settings)
    jwk = keys.get(kid)
    if jwk is None:
        reset_jwks_cache()  # the signing key may have rotated
        keys = _fetch_jwks(settings)
        jwk = keys.get(kid)
    if jwk is None:
        raise _unauthorized("Invalid token.")

    try:
        public_key = jwt.PyJWK(jwk).key
        claims = jwt.decode(
            token,
            public_key,
            algorithms=sorted(ALLOWED_ALGS),
            audience="authenticated",
            options={"require": ["sub", "exp", "aud"]},
        )
    except Exception:
        logger.warning("token verification failed")
        raise _unauthorized("Invalid or expired token.") from None

    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        raise _unauthorized("Invalid token.")
    return sub


async def current_identity(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer),
) -> database.Identity:
    """Verify the caller and load their role from profiles.

    This is the ONLY source of identity for every authenticated route.
    """
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Missing bearer token.")
    if (credentials.scheme or "").lower() != "bearer":
        raise _unauthorized("Missing bearer token.")

    settings: config.Settings = request.app.state.settings
    user_id = verify_token(credentials.credentials, settings)

    # Role comes from the database, never from the token.
    try:
        with database.session(
            settings.database_url, database.Identity(user_id, "authenticated")
        ) as conn:
            role = database.load_role(conn, user_id)
    except database.DatabaseError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Identity service unavailable.",
        ) from None

    if role is None:
        # Valid token but no profiles row. Migration 012 normally prevents
        # this; treat it as forbidden rather than creating a row here.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No profile is associated with this account.",
        )

    identity = database.Identity(user_id, role)
    request.state.identity = identity
    return identity


async def current_admin(
    identity: database.Identity = Depends(current_identity),
) -> database.Identity:
    """Require an authenticated admin.

    Depends on current_identity, so the JWT is verified first and the role is
    read from the database - a token can never claim admin.
    """
    if not identity.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required.",
        )
    return identity

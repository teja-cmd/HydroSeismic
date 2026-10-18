from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
import os
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

import jwt
from fastapi import Depends, Header, HTTPException
from jwt.exceptions import PyJWKClientConnectionError, PyJWTError


class Role(str, Enum):
    REQUESTER = "requester"
    GOVERNMENT_OFFICER = "government_officer"
    WAREHOUSE_STAFF = "warehouse_staff"
    ADMINISTRATOR = "administrator"
    AUDITOR = "auditor"


@dataclass(frozen=True)
class Principal:
    subject: str
    roles: frozenset[Role]


ROLE_ALIASES = {
    "requester": Role.REQUESTER,
    "relief_requester": Role.REQUESTER,
    "requesters": Role.REQUESTER,
    "government_officer": Role.GOVERNMENT_OFFICER,
    "government_officers": Role.GOVERNMENT_OFFICER,
    "gov_officer": Role.GOVERNMENT_OFFICER,
    "gov_officers": Role.GOVERNMENT_OFFICER,
    "warehouse_staff": Role.WAREHOUSE_STAFF,
    "warehouse": Role.WAREHOUSE_STAFF,
    "administrator": Role.ADMINISTRATOR,
    "administrators": Role.ADMINISTRATOR,
    "admin": Role.ADMINISTRATOR,
    "auditor": Role.AUDITOR,
    "auditors": Role.AUDITOR,
}


def _role_values(claim: Any) -> Iterable[str]:
    if isinstance(claim, str):
        return (claim,)
    if isinstance(claim, list):
        return (value for value in claim if isinstance(value, str))
    return ()


def _configured_value(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise HTTPException(
            status_code=503,
            detail=f"Identity provider configuration is missing {name}",
        )
    return value


@lru_cache(maxsize=8)
def _jwks_client(jwks_url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(jwks_url, cache_jwk_set=True)


def verify_token(token: str) -> dict[str, Any]:
    issuer = _configured_value("HYDROSEISMIC_OIDC_ISSUER")
    audience = _configured_value("HYDROSEISMIC_OIDC_AUDIENCE")
    jwks_url = _configured_value("HYDROSEISMIC_OIDC_JWKS_URL")
    for setting, value in (
        ("HYDROSEISMIC_OIDC_ISSUER", issuer),
        ("HYDROSEISMIC_OIDC_JWKS_URL", jwks_url),
    ):
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise HTTPException(
                status_code=503,
                detail=f"{setting} must be an HTTPS URL",
            )
    try:
        signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256", "ES256"],
            audience=audience,
            issuer=issuer,
            options={"require": ["exp", "sub"]},
        )
    except PyJWKClientConnectionError as exc:
        raise HTTPException(
            status_code=503,
            detail="Identity provider could not be reached",
        ) from exc
    except PyJWTError as exc:
        raise HTTPException(
            status_code=401,
            detail="Bearer token is invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return claims


def principal_from_claims(claims: dict[str, Any]) -> Principal:
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise HTTPException(status_code=401, detail="Token has no valid subject")

    role_claim = os.getenv("HYDROSEISMIC_ROLE_CLAIM", "roles").strip() or "roles"
    raw_roles = claims.get(role_claim, [])
    roles = frozenset(
        ROLE_ALIASES[normalized]
        for value in _role_values(raw_roles)
        if (normalized := value.strip().lower().replace("-", "_").replace(" ", "_"))
        in ROLE_ALIASES
    )
    return Principal(subject=subject.strip(), roles=roles)


def get_current_principal(
    authorization: str | None = Header(default=None),
) -> Principal:
    if not authorization:
        raise HTTPException(
            status_code=401,
            detail="Bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    scheme, separator, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not separator or not token.strip():
        raise HTTPException(
            status_code=401,
            detail="Bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal_from_claims(verify_token(token.strip()))


def require_roles(*allowed: Role) -> Callable[..., Principal]:
    def dependency(
        principal: Principal = Depends(get_current_principal),
    ) -> Principal:
        if not principal.roles.intersection(allowed):
            raise HTTPException(status_code=403, detail="Insufficient role")
        return principal

    return dependency


REVIEWER_ROLES = (Role.GOVERNMENT_OFFICER, Role.ADMINISTRATOR)
REQUESTER_ROLES = (Role.REQUESTER, Role.GOVERNMENT_OFFICER, Role.ADMINISTRATOR)
WAREHOUSE_ROLES = (Role.WAREHOUSE_STAFF, Role.ADMINISTRATOR)
AUDIT_ROLES = (Role.AUDITOR, Role.ADMINISTRATOR)
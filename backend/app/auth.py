from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Protocol

import jwt
from fastapi import Depends, Request

from . import service
from .config import (
    DIAGNOSTICS_AUTH_ROLE_PUBLIC,
    AUTH_MODE_NONE,
    AUTH_MODE_OIDC_DRY_RUN,
    AUTH_MODE_OIDC_ENFORCED,
    JWT_SHARED_SECRET,
    JWT_SIGNING_ALGORITHMS,
    JWT_VERIFIER,
    JWT_VERIFIER_JWKS,
    JWT_VERIFIER_SHARED_SECRET,
    OIDC_JWKS_URL,
    OIDC_ALLOWED_HOSTED_DOMAINS,
    OIDC_EXPECTED_AUDIENCE,
    OIDC_EXPECTED_ISSUER,
    OIDC_PROVIDER,
    OIDC_REQUIRE_EMAIL_VERIFIED,
    RBAC_MODE_DRY_RUN,
    RBAC_MODE_ENFORCED,
    RBAC_MODE_NONE,
    get_auth_mode,
    get_diagnostics_auth_role,
    get_rbac_mode,
)
from .db import get_connection
from .errors import AppError

VALID_ROLES = {"admin", "operator", "viewer"}
ROLE_PRIORITY = {"viewer": 1, "operator": 2, "admin": 3}

OPERATOR_GET_PATTERNS = [
    re.compile(r"^/api/artifacts(?:/[^/]+(?:/download)?)?$"),
    re.compile(r"^/api/.+/import-template$"),
    re.compile(r"^/api/.+/import-reference$"),
    re.compile(r"^/api/.+/import-jobs(?:/[^/]+)?$"),
    re.compile(r"^/api/workspace/planning-export(?:-multi)?$"),
    re.compile(r"^/api/procurement-batches/[^/]+/export\.csv$"),
]
ADMIN_ENDPOINT_PATTERNS: list[tuple[set[str], re.Pattern[str]]] = [
    ({"GET", "POST"}, re.compile(r"^/api/users$")),
    ({"GET", "PUT", "DELETE"}, re.compile(r"^/api/users/\d+$")),
]


@dataclass(frozen=True)
class RequestIdentity:
    subject: str
    email: str | None
    provider: str
    claims: dict[str, Any]
    hosted_domain: str | None = None
    issuer: str | None = None
    audience: str | list[str] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class IdentityResolver(Protocol):
    def resolve(self, request: Request) -> RequestIdentity | None: ...


def normalize_role(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized not in VALID_ROLES:
        raise AppError(
            code="INVALID_ROLE",
            message="Role must be one of admin, operator, or viewer",
            status_code=422,
        )
    return normalized


def request_user_role(request: Request) -> str | None:
    user = getattr(request.state, "user", None)
    if not isinstance(user, dict):
        return None
    role = user.get("role")
    return normalize_role(str(role)) if role else None


def role_satisfies(actual_role: str | None, required_role: str) -> bool:
    if actual_role is None:
        return False
    return ROLE_PRIORITY.get(actual_role, 0) >= ROLE_PRIORITY[required_role]


def normalize_http_method(method: str) -> str:
    normalized = method.upper()
    if normalized == "HEAD":
        return "GET"
    return normalized


def required_role_for_request(request: Request) -> str | None:
    path = request.url.path
    method = normalize_http_method(request.method)
    if request.method.upper() == "OPTIONS":
        return None
    if path in {"/healthz", "/readyz"}:
        return None
    if method == "GET" and path in {"/api/health", "/api/auth/capabilities"}:
        diagnostics_role = get_diagnostics_auth_role()
        if diagnostics_role == DIAGNOSTICS_AUTH_ROLE_PUBLIC:
            return None
        return diagnostics_role
    if path == "/api/users/me":
        return "viewer"
    for methods, pattern in ADMIN_ENDPOINT_PATTERNS:
        if method in methods and pattern.match(path):
            return "admin"
    if path.startswith("/api/"):
        if method == "GET":
            if any(pattern.match(path) for pattern in OPERATOR_GET_PATTERNS):
                return "operator"
            return "viewer"
        return "operator"
    return None


def endpoint_policy_summary() -> dict[str, list[str]]:
    diagnostics_role = get_diagnostics_auth_role()
    public_paths = ["/healthz", "/readyz"]
    diagnostics_paths = ["/api/health", "/api/auth/capabilities"]
    viewer_paths = [
        "default: GET /api/** except public, operator-only exports/downloads, and admin users surfaces",
        "/api/users/me",
    ]
    operator_paths = [
        "default: non-GET /api/** except admin users surfaces",
        "/api/artifacts/**",
        "/api/**/import-template",
        "/api/**/import-reference",
        "/api/**/import-jobs/**",
        "/api/workspace/planning-export",
        "/api/workspace/planning-export-multi",
        "/api/procurement-batches/{batch_id}/export.csv",
    ]
    admin_paths = [
        "GET /api/users",
        "POST /api/users",
        "GET /api/users/{user_id}",
        "PUT /api/users/{user_id}",
        "DELETE /api/users/{user_id}",
    ]
    if diagnostics_role == DIAGNOSTICS_AUTH_ROLE_PUBLIC:
        public_paths.extend(diagnostics_paths)
    elif diagnostics_role == "viewer":
        viewer_paths.extend(diagnostics_paths)
    elif diagnostics_role == "operator":
        operator_paths.extend(diagnostics_paths)
    else:
        admin_paths.extend(diagnostics_paths)
    return {
        "public": sorted(public_paths),
        "viewer": viewer_paths,
        "operator": operator_paths,
        "admin": admin_paths,
    }


def _validated_email_claim(payload: dict[str, Any]) -> str | None:
    email = _normalized_optional_text(payload.get("email"), lower=True)
    if email and OIDC_REQUIRE_EMAIL_VERIFIED and payload.get("email_verified") is not True:
        raise AppError(
            code="INVALID_TOKEN",
            message="Verified email claim is required when email is present",
            status_code=401,
        )
    return email


class SharedSecretJwtVerifier:
    def __init__(self) -> None:
        if not JWT_SHARED_SECRET:
            raise AppError(
                code="AUTH_CONFIGURATION_ERROR",
                message="JWT_SHARED_SECRET must be configured for bearer token verification",
                status_code=500,
            )

    def verify(self, token: str) -> RequestIdentity:
        options = {"require": ["sub"]}
        decode_kwargs: dict[str, Any] = {
            "algorithms": JWT_SIGNING_ALGORITHMS,
            "options": options,
        }
        if OIDC_EXPECTED_AUDIENCE:
            decode_kwargs["audience"] = OIDC_EXPECTED_AUDIENCE
        else:
            decode_kwargs["options"] = {**options, "verify_aud": False}
        if OIDC_EXPECTED_ISSUER:
            decode_kwargs["issuer"] = OIDC_EXPECTED_ISSUER
        payload = jwt.decode(token, JWT_SHARED_SECRET, **decode_kwargs)
        subject = str(payload.get("sub") or "").strip()
        if not subject:
            raise AppError(code="INVALID_TOKEN", message="JWT subject claim is required", status_code=401)
        email = _validated_email_claim(payload)
        hosted_domain = _normalized_optional_text(payload.get("hd"), lower=True)
        if OIDC_ALLOWED_HOSTED_DOMAINS and hosted_domain not in OIDC_ALLOWED_HOSTED_DOMAINS:
            raise AppError(
                code="INVALID_TOKEN",
                message="JWT hosted domain is not allowed",
                status_code=401,
                details={
                    "allowed_hosted_domains": OIDC_ALLOWED_HOSTED_DOMAINS,
                    "hosted_domain": hosted_domain,
                },
            )
        audience = payload.get("aud")
        issuer = _normalized_optional_text(payload.get("iss"))
        return RequestIdentity(
            subject=subject,
            email=email,
            provider=OIDC_PROVIDER,
            claims=dict(payload),
            hosted_domain=hosted_domain,
            issuer=issuer,
            audience=audience if isinstance(audience, (str, list)) else None,
        )


class JwtIdentityResolver:
    def __init__(self, verifier: SharedSecretJwtVerifier) -> None:
        self._verifier = verifier

    def resolve(self, request: Request) -> RequestIdentity | None:
        raw_value = (request.headers.get("Authorization") or "").strip()
        if not raw_value:
            return None
        scheme, _, token = raw_value.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise AppError(
                code="INVALID_AUTHORIZATION_HEADER",
                message="Authorization header must use Bearer token format",
                status_code=401,
            )
        return self._verifier.verify(token.strip())


class JwksJwtVerifier:
    def __init__(self) -> None:
        if not OIDC_JWKS_URL:
            raise AppError(
                code="AUTH_CONFIGURATION_ERROR",
                message="OIDC_JWKS_URL must be configured when JWT_VERIFIER=jwks",
                status_code=500,
            )
        self._client = jwt.PyJWKClient(OIDC_JWKS_URL)

    def verify(self, token: str) -> RequestIdentity:
        signing_key = self._client.get_signing_key_from_jwt(token)
        options = {"require": ["sub"]}
        decode_kwargs: dict[str, Any] = {
            "algorithms": JWT_SIGNING_ALGORITHMS,
            "options": options,
        }
        if OIDC_EXPECTED_AUDIENCE:
            decode_kwargs["audience"] = OIDC_EXPECTED_AUDIENCE
        else:
            decode_kwargs["options"] = {**options, "verify_aud": False}
        if OIDC_EXPECTED_ISSUER:
            decode_kwargs["issuer"] = OIDC_EXPECTED_ISSUER
        payload = jwt.decode(token, signing_key.key, **decode_kwargs)
        subject = str(payload.get("sub") or "").strip()
        if not subject:
            raise AppError(code="INVALID_TOKEN", message="JWT subject claim is required", status_code=401)
        email = _validated_email_claim(payload)
        hosted_domain = _normalized_optional_text(payload.get("hd"), lower=True)
        if OIDC_ALLOWED_HOSTED_DOMAINS and hosted_domain not in OIDC_ALLOWED_HOSTED_DOMAINS:
            raise AppError(
                code="INVALID_TOKEN",
                message="JWT hosted domain is not allowed",
                status_code=401,
                details={
                    "allowed_hosted_domains": OIDC_ALLOWED_HOSTED_DOMAINS,
                    "hosted_domain": hosted_domain,
                },
            )
        audience = payload.get("aud")
        issuer = _normalized_optional_text(payload.get("iss"))
        return RequestIdentity(
            subject=subject,
            email=email,
            provider=OIDC_PROVIDER,
            claims=dict(payload),
            hosted_domain=hosted_domain,
            issuer=issuer,
            audience=audience if isinstance(audience, (str, list)) else None,
        )


def build_identity_resolver() -> IdentityResolver:
    if JWT_VERIFIER == JWT_VERIFIER_SHARED_SECRET:
        return JwtIdentityResolver(SharedSecretJwtVerifier())
    if JWT_VERIFIER == JWT_VERIFIER_JWKS:
        return JwtIdentityResolver(JwksJwtVerifier())
    raise AppError(
        code="AUTH_CONFIGURATION_ERROR",
        message=f"Unsupported JWT_VERIFIER '{JWT_VERIFIER}'",
        status_code=500,
    )


def map_identity_to_user(database_url: str | None, identity: RequestIdentity) -> dict[str, Any] | None:
    conn = get_connection(database_url)
    try:
        return service.get_active_user_by_identity(
            conn,
            email=identity.email,
            external_subject=identity.subject,
            identity_provider=identity.provider,
            hosted_domain=identity.hosted_domain,
        )
    finally:
        conn.close()


def auth_allows_dry_run() -> bool:
    return get_auth_mode() == AUTH_MODE_OIDC_DRY_RUN


def auth_is_enforced() -> bool:
    return get_auth_mode() == AUTH_MODE_OIDC_ENFORCED


def rbac_allows_dry_run() -> bool:
    return get_rbac_mode() == RBAC_MODE_DRY_RUN


def rbac_is_enforced() -> bool:
    return get_rbac_mode() == RBAC_MODE_ENFORCED


def authorization_mode_summary() -> dict[str, Any]:
    auth_mode = get_auth_mode()
    rbac_mode = get_rbac_mode()
    return {
        "auth_mode": auth_mode,
        "auth_enforced": auth_mode == AUTH_MODE_OIDC_ENFORCED,
        "auth_dry_run": auth_mode == AUTH_MODE_OIDC_DRY_RUN,
        "rbac_mode": rbac_mode,
        "rbac_enforced": rbac_mode == RBAC_MODE_ENFORCED,
        "rbac_dry_run": rbac_mode == RBAC_MODE_DRY_RUN,
        "planned_roles": ["admin", "operator", "viewer"],
        "jwt_verifier": JWT_VERIFIER,
        "oidc_provider": OIDC_PROVIDER,
        "oidc_expected_issuer": OIDC_EXPECTED_ISSUER or None,
        "oidc_expected_audience": OIDC_EXPECTED_AUDIENCE or None,
        "oidc_jwks_configured": bool(OIDC_JWKS_URL),
        "diagnostics_auth_role": get_diagnostics_auth_role(),
    }


def require_role(required_role: str):
    normalized_required_role = normalize_role(required_role)
    if normalized_required_role is None:
        raise ValueError("required_role must be a non-empty role name")

    def _dependency(request: Request):
        user = getattr(request.state, "user", None)
        if normalized_required_role == "viewer":
            if user is None and get_auth_mode() != AUTH_MODE_NONE:
                raise AppError(code="AUTH_REQUIRED", message="Bearer token is required", status_code=401)
            return
        actual_role = request_user_role(request)
        if role_satisfies(actual_role, normalized_required_role):
            return
        if get_auth_mode() == AUTH_MODE_NONE and get_rbac_mode() == RBAC_MODE_NONE:
            return
        raise AppError(
            code="FORBIDDEN",
            message=f"{normalized_required_role.capitalize()} role is required for this endpoint",
            status_code=403,
            details={"required_role": normalized_required_role, "actual_role": actual_role},
        )

    return Depends(_dependency)


def _normalized_optional_text(value: Any, *, lower: bool = False) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    return normalized.lower() if lower else normalized

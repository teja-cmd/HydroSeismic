from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from backend.auth.authorization import (
    Role,
    get_current_principal,
    principal_from_claims,
    require_roles,
)


class AuthorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.public_key = cls.private_key.public_key()

    def make_token(self, *, issuer: str = "https://identity.example.org/") -> str:
        return jwt.encode(
            {
                "iss": issuer,
                "aud": "hydroseismic-api",
                "sub": "officer-42",
                "roles": ["government_officer"],
                "exp": datetime.now(timezone.utc) + timedelta(minutes=2),
            },
            self.private_key,
            algorithm="RS256",
        )

    def test_valid_oidc_token_produces_verified_principal(self) -> None:
        settings = {
            "HYDROSEISMIC_OIDC_ISSUER": "https://identity.example.org/",
            "HYDROSEISMIC_OIDC_AUDIENCE": "hydroseismic-api",
            "HYDROSEISMIC_OIDC_JWKS_URL": "https://identity.example.org/keys",
        }
        jwks_client = SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=self.public_key)
        )
        with patch.dict(os.environ, settings, clear=True), patch(
            "backend.auth.authorization._jwks_client", return_value=jwks_client
        ):
            principal = get_current_principal(f"Bearer {self.make_token()}")

        self.assertEqual(principal.subject, "officer-42")
        self.assertEqual(principal.roles, frozenset({Role.GOVERNMENT_OFFICER}))

    def test_wrong_issuer_is_rejected(self) -> None:
        settings = {
            "HYDROSEISMIC_OIDC_ISSUER": "https://identity.example.org/",
            "HYDROSEISMIC_OIDC_AUDIENCE": "hydroseismic-api",
            "HYDROSEISMIC_OIDC_JWKS_URL": "https://identity.example.org/keys",
        }
        jwks_client = SimpleNamespace(
            get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=self.public_key)
        )
        with patch.dict(os.environ, settings, clear=True), patch(
            "backend.auth.authorization._jwks_client", return_value=jwks_client
        ), self.assertRaises(HTTPException) as raised:
            get_current_principal(f"Bearer {self.make_token(issuer='https://wrong.example/')}")

        self.assertEqual(raised.exception.status_code, 401)

    def test_missing_provider_configuration_fails_closed(self) -> None:
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(HTTPException) as raised:
            get_current_principal("Bearer unverified-token")

        self.assertEqual(raised.exception.status_code, 503)

    def test_non_https_provider_configuration_is_rejected(self) -> None:
        settings = {
            "HYDROSEISMIC_OIDC_ISSUER": "http://identity.example.org/",
            "HYDROSEISMIC_OIDC_AUDIENCE": "hydroseismic-api",
            "HYDROSEISMIC_OIDC_JWKS_URL": "http://identity.example.org/keys",
        }
        with patch.dict(os.environ, settings, clear=True), self.assertRaises(HTTPException) as raised:
            get_current_principal(f"Bearer {self.make_token()}")

        self.assertEqual(raised.exception.status_code, 503)

    def test_missing_bearer_token_is_unauthorized(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            get_current_principal(None)

        self.assertEqual(raised.exception.status_code, 401)

    def test_configured_role_claim_maps_roles(self) -> None:
        with patch.dict(os.environ, {"HYDROSEISMIC_ROLE_CLAIM": "groups"}, clear=True):
            principal = principal_from_claims(
                {"sub": "warehouse-1", "groups": ["Warehouse Staff", "auditor"]}
            )

        self.assertEqual(
            principal.roles,
            frozenset({Role.WAREHOUSE_STAFF, Role.AUDITOR}),
        )

    def test_role_dependency_rejects_wrong_role(self) -> None:
        dependency = require_roles(Role.GOVERNMENT_OFFICER)
        with self.assertRaises(HTTPException) as raised:
            dependency(principal_from_claims({"sub": "auditor-1", "roles": ["auditor"]}))

        self.assertEqual(raised.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
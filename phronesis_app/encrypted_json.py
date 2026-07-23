# ==============================================================================
# File: phronesis_app/encrypted_json.py
# Description: VN-E05 Fernet-encrypted JSONField for calendar OAuth credentials
# Component: Core / Security
# Version: 1.0 (Gold Master)
# Created: 2026-07-22
# Last Update: 2026-07-22
# ==============================================================================
"""Transparent Fernet encryption for JSON blobs at rest (S-31 / VN-E05).

Key resolution (first match wins for *encryption*):
1. ``PHRONESIS_CREDENTIALS_KEY`` — Fernet url-safe base64 32-byte key
2. Derived from Django ``SECRET_KEY`` (sha256 + urlsafe_b64)

Decryption also tries ``PHRONESIS_CREDENTIALS_KEY_PREVIOUS`` so operators can
rotate the dedicated key without bricking calendar tokens.

Envelope stored in the JSON column::

    {"__phronesis_enc__": "<fernet-token>", "__v": 1}

Plaintext dicts already in the DB decrypt as-is (lazy upgrade on next write).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.db import models

logger = logging.getLogger(__name__)

ENC_MARKER = "__phronesis_enc__"
ENC_VERSION_KEY = "__v"
ENC_VERSION = 1
_DERIVE_PREFIX = "phronesis-credentials-v1:"


def _normalize_fernet_key(raw: str) -> bytes:
    """Accept a Fernet key string; raise ValueError if invalid."""
    key = raw.strip().encode("ascii")
    # Validate early so misconfigured env fails at startup/use, not silently.
    Fernet(key)
    return key


def _derived_key_from_secret() -> bytes:
    digest = hashlib.sha256(
        f"{_DERIVE_PREFIX}{settings.SECRET_KEY}".encode("utf-8")
    ).digest()
    return base64.urlsafe_b64encode(digest)


def credentials_fernet() -> MultiFernet:
    """Build MultiFernet: primary encrypt key first, optional previous for decrypt."""
    fernets: list[Fernet] = []
    primary = (os.environ.get("PHRONESIS_CREDENTIALS_KEY") or "").strip()
    previous = (os.environ.get("PHRONESIS_CREDENTIALS_KEY_PREVIOUS") or "").strip()
    if primary:
        fernets.append(Fernet(_normalize_fernet_key(primary)))
    else:
        fernets.append(Fernet(_derived_key_from_secret()))
    if previous:
        fernets.append(Fernet(_normalize_fernet_key(previous)))
    return MultiFernet(fernets)


def is_encrypted_credentials(value: Any) -> bool:
    """True when *value* is our Fernet envelope dict."""
    return (
        isinstance(value, dict)
        and ENC_MARKER in value
        and isinstance(value.get(ENC_MARKER), str)
    )


def encrypt_credentials_payload(value: Any) -> Any:
    """Return Fernet envelope for a JSON-serializable mapping; pass through empty/None.

    Already-encrypted envelopes are returned unchanged (idempotent).
    """
    if value is None:
        return None
    if value == {} or value == []:
        return value
    if is_encrypted_credentials(value):
        return value
    if not isinstance(value, (dict, list)):
        # Non-mapping leftovers: leave alone rather than corrupt the column.
        return value
    token = credentials_fernet().encrypt(
        json.dumps(value, separators=(",", ":"), default=str).encode("utf-8")
    )
    return {ENC_MARKER: token.decode("ascii"), ENC_VERSION_KEY: ENC_VERSION}


def decrypt_credentials_payload(value: Any) -> Any:
    """Decrypt Fernet envelope to plaintext dict/list; pass through plaintext.

    Raises ``InvalidToken`` if the envelope cannot be decrypted with configured keys.
    """
    if value is None or not is_encrypted_credentials(value):
        return value
    token = value[ENC_MARKER].encode("ascii")
    plaintext = credentials_fernet().decrypt(token)
    return json.loads(plaintext.decode("utf-8"))


class EncryptedJSONField(models.JSONField):
    """JSONField that Fernet-encrypts non-empty values before persisting (VN-E05).

    Application code continues to read/write ordinary dicts. Backup serializers
    see decrypted Python values and must still scrub secrets (S-41).
    """

    description = "Fernet-encrypted JSON"

    def from_db_value(self, value, expression, connection):  # noqa: ANN001
        value = super().from_db_value(value, expression, connection)
        if value is None:
            return value
        try:
            return decrypt_credentials_payload(value)
        except InvalidToken:
            logger.error(
                "Failed to decrypt EncryptedJSONField value; "
                "check PHRONESIS_CREDENTIALS_KEY / SECRET_KEY rotation."
            )
            raise

    def get_prep_value(self, value: Any) -> Any:
        prepared = encrypt_credentials_payload(value)
        return super().get_prep_value(prepared)

    def value_to_string(self, obj: models.Model) -> str:
        # Serialization for fixtures/dumps: emit decrypted JSON so scrubbers work.
        value = self.value_from_object(obj)
        return json.dumps(value, default=str)

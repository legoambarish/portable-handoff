"""Canonical payload hashing for tamper-evident capsules."""

from __future__ import annotations

import copy
import hashlib
import hmac
from typing import Any

from .errors import IntegrityError
from .models import validate_document
from .strict_json import canonical_bytes


def payload_without_integrity(document: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(document)
    payload.pop("integrity", None)
    return payload


def digest_document(document: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_bytes(payload_without_integrity(document))).hexdigest()


def with_integrity(document: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(validate_document({**document, "integrity": {"algorithm": "sha256", "digest": "0" * 64}}))
    result["integrity"] = {"algorithm": "sha256", "digest": digest_document(result)}
    return validate_document(result)


def verify_integrity(document: dict[str, Any]) -> None:
    expected = digest_document(document)
    actual = document.get("integrity", {}).get("digest") if isinstance(document.get("integrity"), dict) else None
    if not isinstance(actual, str) or not hmac.compare_digest(expected, actual):
        raise IntegrityError()


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

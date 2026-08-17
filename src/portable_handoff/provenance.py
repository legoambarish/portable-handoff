"""Helpers for explicit provenance and trust labels."""

from __future__ import annotations

from typing import Any

from .models import Provenance, Trust


def claim(text: str, *, provenance: str = Provenance.MODEL_INFERENCE.value, trust: str = Trust.INFERRED.value, evidence_refs: list[str] | None = None, captured_at: str | None = None) -> dict[str, Any]:
    return {"text": text, "provenance": provenance, "trust": trust, "evidence_refs": list(evidence_refs or []), "captured_at": captured_at}


def evidence(evidence_id: str, *, kind: str, source: str, digest: str | None, summary: str, provenance: str = Provenance.TOOL.value, trust: str = Trust.OBSERVED.value, captured_at: str | None = None) -> dict[str, Any]:
    return {"evidence_id": evidence_id, "kind": kind, "source": source, "digest": digest, "summary": summary, "captured_at": captured_at, "provenance": provenance, "trust": trust}

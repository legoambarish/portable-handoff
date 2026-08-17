"""Capsule validation, integrity checking, and Markdown/JSON drift detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .canonical import verify_integrity
from .errors import HandoffError, IntegrityError, SchemaError
from .models import validate_document
from .parse import ParsedCapsule, parse_capsule
from .render import render_capsule
from .storage import read_capsule


@dataclass
class ValidationReport:
    valid: bool
    code: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    document: dict[str, Any] | None = None

    def to_dict(self, *, include_document: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {"valid": self.valid, "code": self.code, "errors": list(self.errors), "warnings": list(self.warnings)}
        if include_document and self.document is not None:
            result["document"] = self.document
        return result


def validate_markdown(markdown: str, *, require_render_match: bool = True) -> ValidationReport:
    try:
        parsed: ParsedCapsule = parse_capsule(markdown)
        document = validate_document(parsed.document)
        verify_integrity(document)
        if require_render_match:
            expected = render_capsule(document).replace("\r\n", "\n")
            actual = markdown.replace("\r\n", "\n")
            if expected.rstrip("\n") != actual.rstrip("\n"):
                raise SchemaError("Markdown sections do not match embedded canonical JSON")
        return ValidationReport(True, 0, document=document)
    except HandoffError as exc:
        return ValidationReport(False, int(exc.code), [exc.message])
    except Exception:
        return ValidationReport(False, 10, ["unexpected capsule validation failure"])


def validate_file(path: str) -> ValidationReport:
    try:
        raw = read_capsule(path)
        return validate_markdown(raw.decode("utf-8"))
    except HandoffError as exc:
        return ValidationReport(False, int(exc.code), [exc.message])
    except UnicodeDecodeError:
        return ValidationReport(False, 5, ["capsule is not valid UTF-8"])
    except FileNotFoundError:
        return ValidationReport(False, 3, ["capsule was not found"])
    except Exception:
        return ValidationReport(False, 10, ["unexpected capsule read failure"])

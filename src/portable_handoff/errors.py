"""Stable, non-secret error types and CLI exit codes."""

from __future__ import annotations

from enum import IntEnum


class ExitCode(IntEnum):
    SUCCESS = 0
    VALIDATION = 2
    SOURCE_NOT_FOUND = 3
    UNSAFE_PATH = 4
    CORRUPT = 5
    LIMIT = 6
    BUSY = 7
    COLLISION = 8
    INTERNAL = 10


def _public_text(value: object, *, maximum: int = 500) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    text = "".join(char if char >= " " and char != "\x7f" else " " for char in text)
    return text[:maximum].strip() or "portable handoff error"


class HandoffError(Exception):
    """Expected failure with a stable exit code and safe public message."""

    def __init__(self, message: str, code: ExitCode = ExitCode.VALIDATION):
        self.message = _public_text(message)
        self.code = ExitCode(code)
        super().__init__(self.message)


class SchemaError(HandoffError):
    def __init__(self, message: str):
        super().__init__(message, ExitCode.VALIDATION)


class IntegrityError(HandoffError):
    def __init__(self, message: str = "capsule integrity verification failed"):
        super().__init__(message, ExitCode.CORRUPT)


class LimitError(HandoffError):
    def __init__(self, message: str = "input exceeds a Portable Handoff safety bound"):
        super().__init__(message, ExitCode.LIMIT)


class UnsafePathError(HandoffError):
    def __init__(self, message: str = "unsafe path rejected"):
        super().__init__(message, ExitCode.UNSAFE_PATH)


class SourceError(HandoffError):
    def __init__(self, message: str = "source is not found or unsupported"):
        super().__init__(message, ExitCode.SOURCE_NOT_FOUND)


class BusySourceError(HandoffError):
    def __init__(self, message: str = "source changed while it was being read"):
        super().__init__(message, ExitCode.BUSY)


class CollisionError(HandoffError):
    def __init__(self, message: str = "output already exists; use --force to replace it"):
        super().__init__(message, ExitCode.COLLISION)

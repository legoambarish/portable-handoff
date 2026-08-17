"""Strict extraction of embedded canonical JSON from Markdown capsules."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .bounds import DEFAULT_BOUNDS, require_bytes
from .errors import SchemaError
from .render import JSON_END, JSON_START, SECTION_ORDER
from .strict_json import loads_strict


@dataclass(frozen=True)
class ParsedCapsule:
    document: dict
    markdown: str
    json_text: str


_JSON_BLOCK_RE = re.compile(
    re.escape(JSON_START) + r"\s*```json\s*\r?\n(?P<body>.*?)\r?\n```\s*" + re.escape(JSON_END),
    re.DOTALL,
)


def _check_section_order(markdown: str) -> None:
    positions: list[int] = []
    for heading in SECTION_ORDER:
        marker = f"## {heading}"
        position = markdown.find(marker)
        if position < 0:
            raise SchemaError(f"capsule is missing section: {heading}")
        positions.append(position)
    if positions != sorted(positions) or len(set(positions)) != len(positions):
        raise SchemaError("capsule sections are out of order")


def extract_embedded_json(markdown: str) -> str:
    if not isinstance(markdown, str):
        raise SchemaError("capsule must be Markdown text")
    require_bytes(markdown.encode("utf-8"), maximum=DEFAULT_BOUNDS.max_capsule_bytes, label="capsule")
    if markdown.count(JSON_START) != 1 or markdown.count(JSON_END) != 1:
        raise SchemaError("capsule must contain one canonical JSON delimiter pair")
    match = _JSON_BLOCK_RE.search(markdown)
    if not match:
        raise SchemaError("canonical JSON block is malformed")
    return match.group("body")


def parse_capsule(markdown: str, *, check_sections: bool = True) -> ParsedCapsule:
    if check_sections:
        _check_section_order(markdown)
    json_text = extract_embedded_json(markdown)
    value = loads_strict(json_text, bounds=DEFAULT_BOUNDS, label="embedded capsule JSON")
    if not isinstance(value, dict):
        raise SchemaError("embedded capsule JSON must be an object")
    return ParsedCapsule(value, markdown, json_text)

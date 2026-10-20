"""
Tool field maps (skills/customer-360/references/tools/*.md) are contracts: every Customer 360
path a map names must exist in the schema, every map carries the sections cs-setup relies on,
and CONNECTORS.md lists exactly the tools that have a map.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Set

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAPS = sorted((ROOT / "skills/customer-360/references/tools").glob("*.md"))
REQUIRED_SECTIONS = [
    "## What the connector exposes",
    "## Matching records to the CRM account",
    "## Setup check",
    "## Field map",
    "## Vocabulary",
    "## Limits and gotchas",
    "## Sources",
]


def _schema_paths() -> Set[str]:
    schema = json.loads((ROOT / "src/schemas/customer_360.json").read_text(encoding="utf-8"))
    defs: Dict[str, Any] = {**schema.get("$defs", {}), **schema.get("definitions", {})}
    out: Set[str] = set()

    def walk(node: Dict[str, Any], prefix: str, depth: int = 0) -> None:
        if depth > 12 or not isinstance(node, dict):
            return
        if "$ref" in node:
            node = defs.get(node["$ref"].split("/")[-1], {})
        for key, sub in (node.get("properties") or {}).items():
            path = f"{prefix}.{key}" if prefix else key
            out.add(path)
            walk(sub, path, depth + 1)
        items = node.get("items")
        if isinstance(items, dict):
            walk(items, prefix + "[]", depth + 1)
        for comb in ("anyOf", "oneOf", "allOf"):
            for sub in node.get(comb) or []:
                walk(sub, prefix, depth + 1)

    walk(schema, "")
    return out


SCHEMA_PATHS = _schema_paths()


def _field_rows(text: str):
    section = text.split("## Field map", 1)[1].split("\n## ", 1)[0]
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4 or cells[0].startswith("---") or cells[0].lower().startswith("customer 360"):
            continue
        yield cells


def test_there_are_tool_maps():
    assert len(MAPS) >= 15


@pytest.mark.parametrize("path", MAPS, ids=lambda p: p.stem)
def test_map_has_required_sections_and_status(path):
    text = path.read_text(encoding="utf-8")
    for heading in REQUIRED_SECTIONS:
        assert heading in text, f"{path.name} is missing '{heading}'"
    assert "**Status:**" in text and "**Category:**" in text and "**Claude connector:**" in text
    sources = text.split("## Sources", 1)[1]
    assert re.search(r"https?://", sources), f"{path.name} cites no source"
    assert chr(0x2014) not in text, f"{path.name} contains an em dash"


@pytest.mark.parametrize("path", MAPS, ids=lambda p: p.stem)
def test_every_mapped_field_exists_in_the_customer_360_schema(path):
    rows = list(_field_rows(path.read_text(encoding="utf-8")))
    assert rows, f"{path.name} has an empty field map"
    for cells in rows:
        found = re.findall(r"`([^`]+)`", cells[0])
        assert len(found) == 1, f"{path.name}: column 1 must hold exactly one backticked path: {cells[0]}"
        field = found[0]
        assert field in SCHEMA_PATHS, f"{path.name}: `{field}` is not a Customer 360 path"
        flag = cells[3]
        assert flag.lower().startswith("none") or re.search(r"`[a-z0-9_]+`", flag), (
            f"{path.name}: the 'If unavailable' column must name a flag in backticks or say none: {flag}")


def test_connectors_page_lists_every_mapped_tool_as_built_against():
    connectors = (ROOT / "CONNECTORS.md").read_text(encoding="utf-8")
    for path in MAPS:
        first = path.read_text(encoding="utf-8").splitlines()[0]
        name = first.lstrip("# ").strip()
        assert f"tools/{path.name}" in connectors, f"CONNECTORS.md does not link the {name} map"


def test_field_sources_index_line_numbers_are_current():
    lines = (ROOT / "skills/customer-360/references/field-sources.md").read_text(encoding="utf-8").split("\n")
    heads = {m.group(1): i for i, line in enumerate(lines, 1) if (m := re.match(r"^## `([^`]+)`", line))}
    for line in lines:
        m = re.match(r"^- `([a-z_0-9]+)`: starts at line (\d+)$", line)
        if m:
            assert heads.get(m.group(1)) == int(m.group(2)), f"field-sources index is stale for `{m.group(1)}`"

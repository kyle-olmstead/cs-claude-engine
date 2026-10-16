"""
Validation CLI used by the plugin skills (and handy on its own).

    python3 src/validate.py c360 <customer_360.json>
    python3 src/validate.py action <file.action.json> --c360 <customer_360.json> [--no-fix]

`c360`   — validates a Customer 360 document against src/schemas/customer_360.json.
`action` — validates a PlaybookAction (bare, or wrapped as {"provenance":..., "action":...})
           against src/schemas/playbook_action.json, resolves every evidence[].source_path
           inside the Customer 360, and applies the code-enforced approval floors (every
           communication and every forecast/commercial CRM write → requires_human_approval=true).
           Floors are written back to the file unless --no-fix is given.

Exit code 0 = valid, 1 = invalid, 2 = usage error. Output is a short human-readable report
followed by a JSON summary line (so a skill can parse it).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.orchestrator import (  # noqa: E402
    EvidenceIntegrityError,
    check_evidence_integrity,
    enforce_approval_floors,
    load_schema,
    validate,
)


def _load(path: Path):
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def cmd_c360(path: Path) -> int:
    doc = _load(path)
    errors = validate(doc, load_schema("customer_360.json"))
    acct = (doc.get("account") or {}).get("account_id", "?")
    if errors:
        print(f"INVALID Customer 360 for {acct}: {len(errors)} error(s)")
        for e in errors[:25]:
            print(f"  - {e}")
        print(json.dumps({"ok": False, "errors": len(errors)}))
        return 1
    flags = doc.get("data_quality_flags") or []
    print(f"VALID Customer 360 for {acct} (schema {doc.get('schema_version')}, as_of {doc.get('as_of_date')})")
    print(json.dumps({"ok": True, "errors": 0, "data_quality_flags": flags}))
    return 0


def cmd_action(path: Path, c360_path: Path, fix: bool) -> int:
    raw = _load(path)
    wrapped = isinstance(raw, dict) and "action" in raw and "provenance" in raw
    action = raw["action"] if wrapped else raw
    c360 = _load(c360_path)

    errors = validate(action, load_schema("playbook_action.json"))
    unresolved = []
    evidence_error = None
    if not errors:
        try:
            unresolved = check_evidence_integrity(action, c360)
        except EvidenceIntegrityError as e:
            evidence_error = str(e)

    before = json.dumps(action, sort_keys=True)
    floored = enforce_approval_floors(json.loads(json.dumps(action)))
    changed = json.dumps(floored, sort_keys=True) != before
    floor_notes = []
    if changed:
        for i, (a, b) in enumerate(zip(action.get("actions", []), floored.get("actions", []))):
            if a.get("requires_human_approval") != b.get("requires_human_approval"):
                floor_notes.append(f"actions[{i}] '{a.get('title')}' → requires_human_approval=true (floor)")
        for i, (a, b) in enumerate(zip(action.get("communications", []), floored.get("communications", []))):
            if a.get("requires_human_approval") != b.get("requires_human_approval"):
                floor_notes.append(f"communications[{i}] → requires_human_approval=true (floor)")
        if fix:
            out = {"provenance": raw["provenance"], "action": floored} if wrapped else floored
            path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    ok = not errors and evidence_error is None
    pb = action.get("playbook_id", "?")
    print(f"{'VALID' if ok else 'INVALID'} PlaybookAction {pb} ({path.name})")
    for e in errors[:25]:
        print(f"  - schema: {e}")
    if evidence_error:
        print(f"  - evidence: {evidence_error}")
    elif unresolved:
        print(f"  - evidence: {len(unresolved)} unresolved path(s) tolerated: {unresolved}")
    for n in floor_notes:
        print(f"  - {n}{' [written]' if fix else ' [not written: --no-fix]'}")
    print(json.dumps({
        "ok": ok, "playbook_id": pb, "schema_errors": len(errors),
        "unresolved_evidence": unresolved, "evidence_error": evidence_error,
        "approval_floors_applied": len(floor_notes), "written": bool(changed and fix),
        "awaiting_approval": sum(1 for a in floored.get("actions", []) if a.get("requires_human_approval")) + len(floored.get("communications", [])),
    }))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Validate Customer 360 documents and PlaybookActions")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("c360"); p1.add_argument("path")
    p2 = sub.add_parser("action"); p2.add_argument("path"); p2.add_argument("--c360", required=True); p2.add_argument("--no-fix", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "c360":
        return cmd_c360(Path(args.path))
    return cmd_action(Path(args.path), Path(args.c360), fix=not args.no_fix)


if __name__ == "__main__":
    sys.exit(main())

"""
Validation CLI used by the plugin skills (and handy on its own).

    python3 src/validate.py c360 <customer_360.json>
    python3 src/validate.py action <file.action.json> --c360 <customer_360.json> [--no-fix]

`c360`:  validates a Customer 360 against src/schemas/customer_360.json.
`action`: validates a PlaybookAction (bare, or wrapped as {"provenance":..., "action":...}):
           schema → evidence paths AND values → recipients are current stakeholders → policy
           floors (communications and commercial/forecast writes need approval; confidence
           < 0.55 lowers priority to P3). Floors are written back unless --no-fix.

Exit 0 = valid, 1 = invalid, 2 = usage error. Human-readable report, then one JSON summary line.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.validation import check_evidence, check_recipients, enforce_policy, schema_errors, validate_c360  # noqa: E402

SCHEMA_DIR = ROOT / "src" / "schemas"


def _load(path: Path):
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def cmd_c360(path: Path) -> int:
    doc = _load(path)
    errors = validate_c360(doc, _load(SCHEMA_DIR / "customer_360.json"))
    acct = (doc.get("account") or {}).get("account_id", "?")
    if errors:
        print(f"INVALID Customer 360 for {acct}: {len(errors)} error(s)")
        for e in errors[:25]:
            print(f"  - {e}")
        print(json.dumps({"ok": False, "errors": len(errors)}))
        return 1
    print(f"VALID Customer 360 for {acct} (schema {doc.get('schema_version')}, as_of {doc.get('as_of_date')})")
    print(json.dumps({"ok": True, "errors": 0, "data_quality_flags": doc.get("data_quality_flags") or []}))
    return 0


def cmd_action(path: Path, c360_path: Path, fix: bool) -> int:
    raw = _load(path)
    wrapped = isinstance(raw, dict) and "action" in raw and "provenance" in raw
    action = raw["action"] if wrapped else raw
    c360 = _load(c360_path)

    errors = schema_errors(action, _load(SCHEMA_DIR / "playbook_action.json"))
    unresolved, ev_errors, rc_errors = [], [], []
    if not errors:
        ev_errors, unresolved = check_evidence(action, c360)
        rc_errors = check_recipients(action, c360)
    changes = enforce_policy(action)
    if changes and fix:
        out = {"provenance": raw["provenance"], "action": action} if wrapped else action
        path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    ok = not errors and not ev_errors and not rc_errors
    pb = action.get("playbook_id", "?")
    print(f"{'VALID' if ok else 'INVALID'} PlaybookAction {pb} ({path.name})")
    for e in errors[:25]:
        print(f"  - schema: {e}")
    for e in ev_errors:
        print(f"  - evidence: {e}")
    for e in rc_errors:
        print(f"  - recipient: {e}")
    if unresolved and not ev_errors:
        print(f"  - evidence: {len(unresolved)} unresolved path(s) tolerated: {unresolved}")
    for c in changes:
        print(f"  - policy: {c}{' [written]' if fix else ' [not written: --no-fix]'}")
    print(json.dumps({
        "ok": ok, "playbook_id": pb, "schema_errors": len(errors), "evidence_errors": len(ev_errors), "recipient_errors": len(rc_errors),
        "unresolved_evidence": unresolved, "policy_changes": changes, "written": bool(changes and fix),
        "awaiting_approval": sum(1 for a in action.get("actions", []) if a.get("requires_human_approval")) + len(action.get("communications", [])),
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

"""
CS-Claude Engine orchestrator (server mode).

Feeds (Customer 360 JSON/JSONL) → validation → enrichment → health recompute → triggers →
per-prompt view → Claude (cached prompts, sliced schema, validated output) → policy floors →
routing (files always; adapters only in live mode).

    python -m src.orchestrator --input examples/sample_customer_360.json --offline --out ./out
    python -m src.orchestrator --input ./feeds/ --csm "Priya Natarajan" --out ./out
    python -m src.orchestrator --input ./feeds/ --triggers-only --out ./out
    python -m src.orchestrator --input ./feeds/ --batch --out ./out        # Messages Batches API

Environment (a .env file in the repo root is loaded automatically):
    ANTHROPIC_API_KEY, CLAUDE_MODEL, CSE_DRY_RUN (default true), CSE_CONCURRENCY (default 8),
    HUBSPOT_ACCESS_TOKEN, SLACK_BOT_TOKEN, SLACK_ALERT_CHANNEL, CLAY_WEBHOOK_URL

The heavy lifting lives in sibling modules: prompts, validation, views, triggers,
claude_client, router, catalogs, testing. This file is wiring and the CLI.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:  # allow `python3 path/to/src/orchestrator.py` (plugin mode)
    sys.path.insert(0, str(_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
except ImportError:  # pragma: no cover
    pass

from src.catalogs import CATALOGS, CATALOG_SCOPES, DEFAULT_BENCHMARKS, VALID_SCOPES  # noqa: E402
from src.claude_client import ClaudeCallResult, ClaudeEmitter, InvalidOutputError  # noqa: E402
from src.models.health_score import HealthScoreDriftError, HealthWeights, assert_no_drift, attach_to_customer_360, compute_health_score  # noqa: E402
from src.prompts import PromptRegistry                                       # noqa: E402
from src.router import ActionRouter, RoutedAction                            # noqa: E402
from src.triggers import Fired, PlaybookSpec, evaluate_triggers, registry_table  # noqa: E402
from src.validation import get_path, resolve_path, validate_c360            # noqa: E402
from src.views import view_for                                               # noqa: E402

log = logging.getLogger("cse.orchestrator")
ROOT = _ROOT
SCHEMA_DIR = ROOT / "src" / "schemas"
DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")


def load_schema(name: str) -> Dict[str, Any]:
    with (SCHEMA_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------------------
# Untrusted text handling (customer-authored fields are data, never instructions)
# --------------------------------------------------------------------------------------

UNTRUSTED_FIELDS = ("sentiment.nps_responses", "sentiment.transcript_signals", "sentiment.verbatim_signals", "support.open_tickets", "lifecycle.kickoff_notes")
_INJECTION_RE = re.compile(r"</?\s*(system|instruction|tool|customer_360|prior_outputs|untrusted_customer_text)\b[^>]*>", re.IGNORECASE)


def sanitize_untrusted(c360: Dict[str, Any]) -> Dict[str, Any]:
    doc = json.loads(json.dumps(c360))

    def scrub(obj: Any) -> Any:
        if isinstance(obj, str):
            return _INJECTION_RE.sub("", obj)
        if isinstance(obj, list):
            return [scrub(x) for x in obj]
        if isinstance(obj, dict):
            return {k: scrub(v) for k, v in obj.items()}
        return obj

    for path in UNTRUSTED_FIELDS:
        ok, val = resolve_path(doc, path)
        if ok and val is not None:
            parts = path.split(".")
            target = doc
            for p in parts[:-1]:
                target = target[p]
            target[parts[-1]] = scrub(val)
    return doc


def wrap_untrusted(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Wrap customer-authored strings in <untrusted_customer_text> tags (after sanitizing)."""
    doc = sanitize_untrusted(doc)
    tag = lambda s: f"<untrusted_customer_text>{s}</untrusted_customer_text>"  # noqa: E731
    for r in get_path(doc, "sentiment.nps_responses", []):
        if r.get("verbatim"):
            r["verbatim"] = tag(r["verbatim"])
    for s in get_path(doc, "sentiment.transcript_signals", []):
        for t in s.get("themes", []):
            if t.get("quoted_evidence"):
                t["quoted_evidence"] = tag(t["quoted_evidence"])
    for t in get_path(doc, "support.open_tickets", []):
        if t.get("subject"):
            t["subject"] = tag(t["subject"])
    if get_path(doc, "lifecycle.kickoff_notes"):
        doc["lifecycle"]["kickoff_notes"] = tag(doc["lifecycle"]["kickoff_notes"])
    return doc


# --------------------------------------------------------------------------------------
# Feed loading
# --------------------------------------------------------------------------------------

def load_feed(path: Path) -> Iterable[Tuple[str, Dict[str, Any]]]:
    """Yield (source_name, document) from .json, .jsonl, a directory of either, or accounts/<id>/customer_360.json."""
    if path.is_dir():
        paths = sorted(p for p in path.iterdir() if p.is_file()) + sorted(path.glob("*/customer_360.json"))
    else:
        paths = [path]
    for p in paths:
        if p.suffix == ".jsonl":
            with p.open(encoding="utf-8") as fh:
                for i, line in enumerate(fh):
                    if line.strip():
                        yield f"{p.name}:{i + 1}", json.loads(line)
        elif p.suffix == ".json":
            with p.open(encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                for i, d in enumerate(data):
                    yield f"{p.name}[{i}]", d
            else:
                yield p.name, data


# --------------------------------------------------------------------------------------
# Orchestrator
# --------------------------------------------------------------------------------------

@dataclass
class AccountRunResult:
    account_id: str
    account_name: str
    health: float
    band: str
    fired: List[str] = field(default_factory=list)
    routed: List[RoutedAction] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class Orchestrator:
    def __init__(self, out_dir: Path, dry_run: bool, offline: bool, csm_name: str, today: Optional[str] = None,
                 catalog_overrides: Optional[Dict[str, Any]] = None, enrich: bool = False, parse_transcripts: bool = False,
                 client: Any = None):
        self.out_dir = out_dir
        self.today = today or datetime.now(timezone.utc).date().isoformat()   # UTC, same clock as provenance.emitted_at
        self.csm_name = csm_name
        self.registry = PromptRegistry(default_model=DEFAULT_MODEL)
        self.c360_schema = load_schema("customer_360.json")
        self.action_schema = load_schema("playbook_action.json")
        overrides = dict(catalog_overrides or {})
        self.catalog_scopes: Dict[str, str] = {**CATALOG_SCOPES, **(overrides.pop("_scopes", None) or {})}
        bad = {k: v for k, v in self.catalog_scopes.items() if v not in VALID_SCOPES}
        if bad:
            raise ValueError(f"catalog scopes must be one of {VALID_SCOPES}: {bad}")
        self.catalogs: Dict[str, Any] = {**CATALOGS, **overrides}
        self.weights = HealthWeights.load()
        self.router = ActionRouter(out_dir, dry_run, self.today)
        self.enrich = enrich and bool(os.environ.get("CLAY_WEBHOOK_URL"))
        self.parse_transcripts = parse_transcripts
        self.offline = offline
        if offline:
            from src.testing import OfflineEmitter
            self.emitter: Any = OfflineEmitter(self.action_schema)
        else:
            if client is None and not os.environ.get("ANTHROPIC_API_KEY"):
                raise SystemExit("ANTHROPIC_API_KEY is not set (use --offline to run without the API)")
            system_prompt = self.registry.get("core.system_csm_orchestrator").render({
                "csm_name": csm_name, "today": self.today, "playbook_registry_table": registry_table(),
                "segment_benchmarks_json": self.catalogs["benchmarks"],
            })
            self.emitter = ClaudeEmitter(self.registry, self.action_schema, system_prompt, client=client)

    # -- inputs -----------------------------------------------------------------------

    def resolve_input(self, spec: str, c360: Dict[str, Any], run_vars: Dict[str, Any]) -> Any:
        """
        Resolve a prompt-header source spec: run:key | c360:path | catalog:name | text:literal | {} | [].

        `catalog:name` is resolved by the catalog's declared scope (src/catalogs.CATALOG_SCOPES, overridable
        with `_scopes` in the --catalogs file): account-scoped catalogs return only this account's entry,
        segment-scoped ones only this segment's, global ones the whole value. A scoped catalog with no entry
        for this account or segment is a miss and the next `|` alternative is tried. The whole catalog is
        never returned as a fallback, so one account's inputs cannot land in another account's prompt.
        """
        account_id = get_path(c360, "account.account_id")
        segment = get_path(c360, "account.segment", "mid_market")
        for alt in (a.strip() for a in spec.split("|")):
            if alt == "{}":
                return {}
            if alt == "[]":
                return []
            kind, _, arg = alt.partition(":")
            if kind == "run" and run_vars.get(arg) is not None:
                return run_vars[arg]
            if kind == "c360":
                ok, v = resolve_path(c360, arg)
                if ok and v is not None:
                    return v
            if kind == "catalog" and arg in self.catalogs:
                cat = self.catalogs[arg]
                scope = self.catalog_scopes.get(arg, "global")
                if scope == "global":
                    return cat
                key = account_id if scope == "account" else segment
                if isinstance(cat, dict) and key in cat:
                    return cat[key]
                continue   # scoped miss: never fall through to the whole catalog
            if kind == "text":
                return arg
        raise KeyError(f"could not resolve input spec {spec!r}")

    def static_vars_for(self, prompt_id: str, c360: Dict[str, Any], run_vars: Dict[str, Any]) -> Dict[str, Any]:
        prompt = self.registry.get(prompt_id)
        out = {name: self.resolve_input(spec, c360, run_vars) for name, spec in prompt.inputs.items()}
        out["playbook_id"] = run_vars.get("playbook_id", "ADHOC")  # used by the offline stub; not a body variable
        return out

    # -- pipeline ---------------------------------------------------------------------

    def prepare(self, c360: Dict[str, Any]) -> Dict[str, Any]:
        errors = validate_c360(c360, self.c360_schema)
        if errors:
            raise ValueError("Customer 360 failed validation: " + "; ".join(errors[:5]))
        seg = c360["account"]["segment"]
        c360.setdefault("benchmarks", {})
        for k, v in self.catalogs["benchmarks"].get(seg, {}).items():
            c360["benchmarks"].setdefault(k, v)
        if self.enrich:
            from src.tools.clay_crm_enrichment import enrich_account_stakeholders
            c360 = enrich_account_stakeholders(c360)
        if self.parse_transcripts:
            from src.tools.call_transcript_parser import parse_and_analyze_pending
            c360 = parse_and_analyze_pending(c360, offline=self.offline)
        result = compute_health_score(c360, self.weights)
        drift_error = None
        try:
            assert_no_drift(result, (c360.get("health") or {}).get("mart_score"))
        except HealthScoreDriftError as e:
            log.error("%s: %s", c360["account"]["account_id"], e)
            drift_error = str(e)
        prepared = attach_to_customer_360(c360, result)
        if drift_error:
            prepared["health"]["drift_error"] = drift_error
        return prepared

    def run_playbook(self, c360: Dict[str, Any], fired: Fired, res: AccountRunResult) -> None:
        spec, account_id = fired.spec, c360["account"]["account_id"]
        prior: Dict[str, Any] = {}
        run_vars = {"today": self.today, "csm_name": self.csm_name, "playbook_id": spec.playbook_id,
                    "variant": "expansion" if spec.playbook_id == "PB-EXP-02" else ("renewal" if spec.playbook_id == "PB-RET-01" else "standard")}
        for prompt_id in spec.prompt_chain:
            try:
                static_vars = self.static_vars_for(prompt_id, c360, run_vars)
                view = wrap_untrusted(view_for(prompt_id, c360))
                instruction = f"Run {spec.playbook_id} via {prompt_id}. Trigger: {fired.reason}."
                if fired.signal_update_for:
                    instruction += (f" An action for this playbook is already open ({fired.signal_update_for}); emit a signal_update "
                                    f"referencing it in related_action_ids instead of a new plan.")
                result = self.emitter.emit(prompt_id, static_vars, view, prior, instruction)
                prior[prompt_id] = result.action
                res.routed.append(self.router.route(c360, prompt_id, result, fired.reason, fired.signal_update_for))
            except InvalidOutputError as e:
                inv = self.out_dir / account_id / "_invalid"
                inv.mkdir(parents=True, exist_ok=True)
                path = inv / f"{spec.playbook_id}.{prompt_id.split('.')[-1]}.json"
                path.write_text(json.dumps({"error": str(e), "attempts": e.attempts}, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
                res.errors.append(f"{spec.playbook_id}/{prompt_id}: invalid output saved for manual review at {path}")
                break
            except Exception as e:
                log.exception("%s %s failed", account_id, prompt_id)
                res.errors.append(f"{spec.playbook_id}/{prompt_id}: {e}")
                break

    def run_account(self, c360: Dict[str, Any], only_playbook: Optional[str] = None) -> AccountRunResult:
        try:
            c360 = self.prepare(c360)
        except Exception as e:
            rej = self.out_dir / "_rejected"
            rej.mkdir(parents=True, exist_ok=True)
            aid = (c360.get("account") or {}).get("account_id", "unknown")
            (rej / f"{aid}.json").write_text(json.dumps({"error": str(e), "document": c360}, indent=2, default=str), encoding="utf-8")
            return AccountRunResult(aid, (c360.get("account") or {}).get("name", "?"), 0.0, "unknown", errors=[str(e)])
        res = AccountRunResult(c360["account"]["account_id"], c360["account"]["name"], c360["health"]["score"], c360["health"]["band"])
        if c360["health"].get("drift_error"):
            res.errors.append(c360["health"]["drift_error"])
        for fired in evaluate_triggers(c360, only_playbook):
            tag = f" [signal_update → {fired.signal_update_for}]" if fired.signal_update_for else ""
            res.fired.append(f"{fired.spec.playbook_id}: {fired.reason}{tag}")
            self.run_playbook(c360, fired, res)
        return res

    def run(self, feed: Path, only_account: Optional[str] = None, only_playbook: Optional[str] = None, concurrency: int = 8) -> Dict[str, Any]:
        docs = [(src, d) for src, d in load_feed(feed) if not only_account or (d.get("account") or {}).get("account_id") == only_account]
        self.out_dir.mkdir(parents=True, exist_ok=True)
        results: List[AccountRunResult] = []
        with cf.ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            for r in pool.map(lambda sd: self.run_account(sd[1], only_playbook), docs):
                results.append(r)
                log.info("%s (%s) health=%.1f %s fired=%s errors=%s", r.account_name, r.account_id, r.health, r.band, r.fired, r.errors)
        summary = self._summary(results)
        (self.out_dir / "run_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        return summary

    def run_batch(self, feed: Path, only_account: Optional[str] = None, only_playbook: Optional[str] = None, poll_s: int = 30) -> Dict[str, Any]:
        """Nightly path: one Batches API submission for every first-stage prompt, then route results. Chained second stages run synchronously."""
        if self.offline:
            raise SystemExit("--batch requires a live client")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        prepared: List[Tuple[Dict[str, Any], Fired]] = []
        results: Dict[str, AccountRunResult] = {}
        for _, d in load_feed(feed):
            if only_account and (d.get("account") or {}).get("account_id") != only_account:
                continue
            try:
                c = self.prepare(d)
            except Exception as e:
                results[d.get("account", {}).get("account_id", "?")] = AccountRunResult("?", "?", 0.0, "unknown", errors=[str(e)])
                continue
            res = AccountRunResult(c["account"]["account_id"], c["account"]["name"], c["health"]["score"], c["health"]["band"])
            results[res.account_id] = res
            for fired in evaluate_triggers(c, only_playbook):
                res.fired.append(f"{fired.spec.playbook_id}: {fired.reason}")
                prepared.append((c, fired))
        items, index = [], {}
        for c, fired in prepared:
            pid = fired.spec.prompt_chain[0]
            run_vars = {"today": self.today, "csm_name": self.csm_name, "playbook_id": fired.spec.playbook_id, "variant": "standard"}
            view = wrap_untrusted(view_for(pid, c))
            cid = f"{c['account']['account_id']}::{fired.spec.playbook_id}::{pid}"
            items.append({"custom_id": cid, "prompt_id": pid, "static_vars": self.static_vars_for(pid, c, run_vars), "c360_view": view,
                          "prior_outputs": {}, "instruction": f"Run {fired.spec.playbook_id} via {pid}. Trigger: {fired.reason}."})
            index[cid] = (c, fired, view)
        if items:
            batch_id = self.emitter.submit_batch(items)
            log.info("submitted batch %s with %d requests", batch_id, len(items))
            for cid, result in self.emitter.collect_batch(batch_id, poll_s).items():
                c, fired, view = index[cid]
                res = results[c["account"]["account_id"]]
                pid = fired.spec.prompt_chain[0]
                try:
                    action = self.emitter.action_from_batch_result(pid, result, view)
                    call = ClaudeCallResult(action, "batch", None, 0, 0, 0, 0, 0.0, 0)
                    res.routed.append(self.router.route(c, pid, call, fired.reason, fired.signal_update_for))
                    if len(fired.spec.prompt_chain) > 1:   # second stage synchronously, with the first as prior output
                        chained = Fired(fired.spec, fired.reason, fired.signal_update_for)
                        self._run_chain_tail(c, chained, res, {pid: action})
                except InvalidOutputError as e:
                    res.errors.append(f"{fired.spec.playbook_id}/{pid}: {e}")
        summary = self._summary(list(results.values()))
        (self.out_dir / "run_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        return summary

    def _run_chain_tail(self, c360: Dict[str, Any], fired: Fired, res: AccountRunResult, prior: Dict[str, Any]) -> None:
        run_vars = {"today": self.today, "csm_name": self.csm_name, "playbook_id": fired.spec.playbook_id,
                    "variant": "expansion" if fired.spec.playbook_id == "PB-EXP-02" else ("renewal" if fired.spec.playbook_id == "PB-RET-01" else "standard")}
        for prompt_id in fired.spec.prompt_chain[1:]:
            try:
                view = wrap_untrusted(view_for(prompt_id, c360))
                result = self.emitter.emit(prompt_id, self.static_vars_for(prompt_id, c360, run_vars), view, prior,
                                           f"Run {fired.spec.playbook_id} via {prompt_id}. Trigger: {fired.reason}.")
                prior[prompt_id] = result.action
                res.routed.append(self.router.route(c360, prompt_id, result, fired.reason, fired.signal_update_for))
            except Exception as e:
                res.errors.append(f"{fired.spec.playbook_id}/{prompt_id}: {e}")

    def triggers_only(self, feed: Path, only_account: Optional[str] = None) -> Dict[str, Any]:
        """Score and evaluate triggers for every document; no Claude calls, no writes beyond triggers.json."""
        self.out_dir.mkdir(parents=True, exist_ok=True)
        rows: List[Dict[str, Any]] = []
        for src, d in load_feed(feed):
            if only_account and (d.get("account") or {}).get("account_id") != only_account:
                continue
            try:
                p = self.prepare(d)
            except Exception as e:
                rows.append({"source": src, "account_id": (d.get("account") or {}).get("account_id"), "error": str(e)})
                continue
            fired = evaluate_triggers(p)
            rows.append({
                "account_id": p["account"]["account_id"], "account_name": p["account"]["name"], "segment": p["account"]["segment"],
                "arr": p["contract"]["arr"], "days_to_renewal": p["contract"]["days_to_renewal"],
                "health": p["health"]["score"], "band": p["health"]["band"], "health_30d_ago": p["health"].get("score_30d_ago"),
                "champion_status": p["relationship"]["champion"]["status"], "ecri": p["sentiment"].get("ecri"),
                "seat_utilization": p["usage"].get("seat_utilization"),
                "fired": [{"playbook_id": f.spec.playbook_id, "priority": f.spec.priority, "reason": f.reason,
                           "prompt_chain": list(f.spec.prompt_chain), "signal_update_for": f.signal_update_for} for f in fired],
                "data_quality_flags": p.get("data_quality_flags", []),
            })
        rows.sort(key=lambda r: (min((int(f["priority"][1]) for f in r.get("fired", [])), default=9), -(r.get("arr") or 0)))
        summary = {
            "run_date": self.today, "accounts": len(rows),
            "by_band": {b: sum(1 for r in rows if r.get("band") == b) for b in ("green", "yellow", "red")},
            "by_priority": {f"P{p}": sum(1 for r in rows for f in r.get("fired", []) if f["priority"] == f"P{p}") for p in range(4)},
            "accounts_detail": rows,
        }
        (self.out_dir / "triggers.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        return summary

    def _summary(self, results: List[AccountRunResult]) -> Dict[str, Any]:
        return {
            "run_date": self.today, "accounts": len(results),
            "actions": sorted(
                [{"account_id": r.account_id, "account_name": r.account_name, "playbook_id": a.playbook_id, "prompt_id": a.prompt_id,
                  "priority": a.priority, "confidence": a.confidence, "awaiting_approval": a.awaiting_approval, "executed": a.executed,
                  "policy_changes": a.policy_changes, "files": a.files} for r in results for a in r.routed],
                key=lambda x: (x["priority"], -x["confidence"]),
            ),
            "errors": [{"account_id": r.account_id, "errors": r.errors} for r in results if r.errors],
            "by_band": {b: sum(1 for r in results if r.band == b) for b in ("green", "yellow", "red", "unknown")},
        }


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="CS-Claude Engine orchestrator")
    ap.add_argument("--input", required=True, help=".json, .jsonl, a directory of either, or accounts/<id>/customer_360.json")
    ap.add_argument("--out", default="./out")
    ap.add_argument("--csm", default="the CSM")
    ap.add_argument("--account-id", default=None)
    ap.add_argument("--playbook", default=None, help="Force a single playbook id (e.g. PB-CAD-01)")
    ap.add_argument("--catalogs", default=None, help="JSON file overriding default catalogs (feature_catalog, pricing, value_milestones, roi_inputs, retention_context, benchmarks)")
    ap.add_argument("--dry-run", action="store_true", help="Write files only; never call adapters (also CSE_DRY_RUN=true)")
    ap.add_argument("--offline", action="store_true", help="No API calls; deterministic stub actions to exercise the pipeline")
    ap.add_argument("--triggers-only", action="store_true", help="Score + evaluate triggers for every account; no Claude calls")
    ap.add_argument("--batch", action="store_true", help="Submit first-stage prompts through the Messages Batches API (nightly runs)")
    ap.add_argument("--enrich", action="store_true", help="Push stale stakeholders to Clay (needs CLAY_WEBHOOK_URL)")
    ap.add_argument("--parse-transcripts", action="store_true")
    ap.add_argument("--concurrency", type=int, default=int(os.environ.get("CSE_CONCURRENCY", "8")))
    ap.add_argument("--today", default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    overrides = json.loads(Path(args.catalogs).read_text(encoding="utf-8")) if args.catalogs else None
    dry_run = args.dry_run or args.offline or args.triggers_only or os.environ.get("CSE_DRY_RUN", "true").lower() == "true"
    orch = Orchestrator(Path(args.out), dry_run, args.offline or args.triggers_only, args.csm, args.today, overrides,
                        enrich=args.enrich, parse_transcripts=args.parse_transcripts)
    if args.triggers_only:
        summary = orch.triggers_only(Path(args.input), args.account_id)
        for r in summary["accounts_detail"]:
            if "error" in r:
                print(f"  ! {r.get('account_id')}: {r['error']}")
                continue
            fired = ", ".join(f"{f['playbook_id']} ({f['reason']})" for f in r["fired"]) or "none"
            print(f"  {r['account_name']} · {r['segment']} · ${r['arr']:,.0f} · {r['days_to_renewal']}d · health {r['health']:.1f} {r['band'].upper()} · champion {r['champion_status']} · fired: {fired}")
        print(json.dumps({k: v for k, v in summary.items() if k != "accounts_detail"}, indent=2))
        print(f"details in {args.out}/triggers.json")
        return 0
    summary = orch.run_batch(Path(args.input), args.account_id, args.playbook) if args.batch else orch.run(Path(args.input), args.account_id, args.playbook, args.concurrency)
    print(json.dumps({k: v for k, v in summary.items() if k != "actions"}, indent=2))
    print(f"{len(summary['actions'])} action(s) written under {args.out}/ — see run_summary.json")
    return 0 if not summary["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())

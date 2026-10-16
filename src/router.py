"""
Action routing: policy floors → files (always) → approval queue / adapters (live mode only).

Dry-run is the default. In live mode only actions that need no approval are executed, through
the adapter for the CRM in use, idempotently via `external_id`. Communications are never sent;
they are written as drafts with approval front-matter.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.claude_client import ClaudeCallResult
from src.validation import enforce_policy

log = logging.getLogger("cse.router")


@dataclass
class RoutedAction:
    account_id: str
    playbook_id: str
    prompt_id: str
    action_id: str
    priority: str
    confidence: float
    awaiting_approval: int
    executed: int
    files: List[str]
    policy_changes: List[str] = field(default_factory=list)


class ActionRouter:
    def __init__(self, out_dir: Path, dry_run: bool, run_date: str):
        self.out_dir = out_dir
        self.dry_run = dry_run
        self.run_date = run_date
        self.hubspot = None
        self.slack = None
        if not dry_run:
            from src.tools.clay_crm_enrichment import HubSpotAdapter, SlackNotifier
            if os.environ.get("HUBSPOT_ACCESS_TOKEN"):
                self.hubspot = HubSpotAdapter(os.environ["HUBSPOT_ACCESS_TOKEN"])
            if os.environ.get("SLACK_BOT_TOKEN"):
                self.slack = SlackNotifier(os.environ["SLACK_BOT_TOKEN"], os.environ.get("SLACK_ALERT_CHANNEL", "#cs-alerts"))

    def route(self, c360: Dict[str, Any], prompt_id: str, result: ClaudeCallResult, trigger_reason: str,
              signal_update_for: Optional[str] = None) -> RoutedAction:
        action = result.action
        policy_changes = enforce_policy(action)
        account_id = c360["account"]["account_id"]
        pb = action["playbook_id"]
        action_id = signal_update_for or f"cse:{account_id}:{pb}:{self.run_date}"
        acct_dir = self.out_dir / account_id
        acct_dir.mkdir(parents=True, exist_ok=True)

        provenance = {
            "action_id": action_id, "prompt_id": prompt_id, "model": result.model, "request_id": result.request_id,
            "input_sha256": hashlib.sha256(json.dumps(c360, sort_keys=True, default=str).encode()).hexdigest(),
            "usage": {"input": result.input_tokens, "output": result.output_tokens,
                      "cache_read": result.cache_read_tokens, "cache_write": result.cache_write_tokens},
            "latency_s": round(result.latency_s, 2), "validation_retries": result.retries, "stop_reason": result.stop_reason,
            "trigger_reason": trigger_reason, "emitted_at": datetime.now(timezone.utc).isoformat(),
            "signal_update_for": signal_update_for, "policy_changes": policy_changes, "dry_run": self.dry_run,
        }
        files: List[str] = []
        suffix = "signal_update" if signal_update_for else "action"
        action_path = acct_dir / f"{pb}.{prompt_id.split('.')[-1]}.{suffix}.json"
        action_path.write_text(json.dumps({"provenance": provenance, "action": action}, indent=2, ensure_ascii=False), encoding="utf-8")
        files.append(str(action_path))

        for i, comm in enumerate(action.get("communications", [])):
            fm = {
                "artifact": f"comm_{comm.get('purpose') or 'message'}", "playbook_id": pb, "account_id": account_id,
                "to": [comm["recipient_contact_id"]], "cc": comm.get("cc_contact_ids", []), "channel": comm["channel"],
                "subject": comm["subject"], "tone": comm["tone_notes"], "send_after_days": comm["send_after_days"],
                "approval_status": "pending", "approved_by": None,
            }
            path = acct_dir / f"{pb}.comm_{i + 1}.md"
            path.write_text("---\n" + "\n".join(f"{k}: {json.dumps(v)}" for k, v in fm.items()) + "\n---\n\n" + comm["body_markdown"] + "\n", encoding="utf-8")
            files.append(str(path))

        awaiting = sum(1 for a in action.get("actions", []) if a.get("requires_human_approval")) + len(action.get("communications", []))
        executed = 0
        if not self.dry_run and not signal_update_for:
            executed = self._execute(c360, action, action_id)
            if self.slack and action["priority"] in ("P0", "P1"):
                self.slack.alert(
                    f"*{action['priority']} {pb}* — {c360['account']['name']} ({account_id})\n"
                    f"{action['diagnosis']['summary'][:400]}\n"
                    f"confidence {action['confidence']:.2f} · {awaiting} item(s) awaiting approval · {action_path.name}"
                )
        return RoutedAction(account_id, pb, prompt_id, action_id, action["priority"], action["confidence"], awaiting, executed, files, policy_changes)

    def _execute(self, c360: Dict[str, Any], action: Dict[str, Any], action_id: str) -> int:
        executed = 0
        for n, a in enumerate(action.get("actions", [])):
            if a.get("requires_human_approval"):
                continue
            ext = f"{action_id}:{n}"
            w = a.get("crm_write")
            try:
                if a["type"] == "crm_write" and w and self.hubspot and w["object"] == "account":
                    self.hubspot.update_account_properties(w.get("object_id") or c360["account"]["account_id"], {w["field"]: w["value"]}, ext)
                    executed += 1
                elif a["type"] == "crm_task" and self.hubspot:
                    self.hubspot.create_task(c360["account"]["account_id"], {"title": a["title"], "body": a["description"], "due_in_days": a["due_in_days"]}, ext)
                    executed += 1
            except Exception as e:  # adapter errors never abort the run
                log.error("adapter error on %s: %s", ext, e)
        return executed

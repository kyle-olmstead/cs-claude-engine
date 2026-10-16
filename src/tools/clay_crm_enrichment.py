"""
Clay enrichment + CRM adapters + champion-change detection.

Three jobs:

1. **Clay enrichment loop.** Push stakeholders whose enrichment is stale to a Clay table via
   its webhook source; Clay runs its waterfall (LinkedIn, Clearbit, Apollo, …) and posts the
   enriched row back to our HTTP endpoint. `ClayResultStore` persists those callbacks so the
   orchestrator can merge them on its next run (or synchronously, if you poll).

2. **Champion-change detection.** Compare the CRM record to the enrichment: employer mismatch,
   title change to a non-buying role, or an explicit `left_company_at`. This is the `JobChange`
   term of the Executive Champion Risk Index (docs/02 §C2).

3. **CRM adapters.** HubSpot and Salesforce implementations of the `CRMAdapter` protocol the
   orchestrator's `ActionRouter` uses. All writes are idempotent via an external id.

    python -m src.tools.clay_crm_enrichment push --input examples/sample_customer_360.json
    python -m src.tools.clay_crm_enrichment ingest --payload clay_callback.json
    python -m src.tools.clay_crm_enrichment detect --input examples/sample_customer_360.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

log = logging.getLogger("cse.enrichment")

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STORE = ROOT / "out" / "_enrichment" / "clay_results.jsonl"

BUYING_ROLE_KEYWORDS = (
    "vp", "vice president", "head of", "director", "chief", "cxo", "ceo", "coo", "cfo", "cio", "cto", "ciso",
    "manager", "lead", "owner", "founder", "president", "general manager", "principal",
)
NON_BUYING_ROLE_KEYWORDS = ("intern", "student", "assistant", "contractor", "consultant", "advisor", "board member")


def normalize_email(email: str) -> str:
    local, _, domain = email.strip().lower().partition("@")
    local = local.split("+", 1)[0]
    return f"{local}@{domain}"


def email_hash(email: str) -> str:
    return hashlib.sha256(normalize_email(email).encode()).hexdigest()


def normalize_company(name: Optional[str]) -> str:
    if not name:
        return ""
    n = name.lower()
    n = re.sub(r"[^\w\s]", " ", n)
    n = re.sub(r"\b(inc|incorporated|llc|ltd|limited|corp|corporation|co|company|plc|gmbh|sa|ag|holdings|group|technologies|technology|the)\b", " ", n)
    return re.sub(r"\s+", " ", n).strip()


# ======================================================================================
# Clay
# ======================================================================================

@dataclass
class ClayPushRow:
    account_id: str
    contact_id: str
    email_hash: str
    full_name: str
    current_title: Optional[str]
    account_name: str
    linkedin_url: Optional[str] = None
    email: Optional[str] = None     # only if the operator allows raw email to leave the warehouse

    def to_payload(self) -> Dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


class ClayClient:
    """
    Clay's "Webhook" source accepts a JSON POST per row (or an array). Results are produced
    by an "HTTP API" enrichment step in the Clay table that POSTs back to `callback_url`.
    """

    def __init__(self, webhook_url: Optional[str] = None, callback_url: Optional[str] = None, api_key: Optional[str] = None, timeout: int = 20):
        self.webhook_url = webhook_url or os.environ.get("CLAY_WEBHOOK_URL")
        self.callback_url = callback_url or os.environ.get("CLAY_CALLBACK_URL")
        self.api_key = api_key or os.environ.get("CLAY_API_KEY")
        self.timeout = timeout
        if not self.webhook_url:
            raise ValueError("CLAY_WEBHOOK_URL not set")

    def push(self, rows: Iterable[ClayPushRow], batch_size: int = 50) -> int:
        if requests is None:
            raise RuntimeError("requests required: pip install requests")
        batch: List[Dict[str, Any]] = []
        sent = 0
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["x-clay-webhook-auth"] = self.api_key
        for row in rows:
            payload = row.to_payload()
            if self.callback_url:
                payload["callback_url"] = self.callback_url
            batch.append(payload)
            if len(batch) >= batch_size:
                sent += self._send(batch, headers)
                batch = []
        if batch:
            sent += self._send(batch, headers)
        return sent

    def _send(self, batch: List[Dict[str, Any]], headers: Dict[str, str]) -> int:
        for attempt in range(4):
            resp = requests.post(self.webhook_url, json=batch, headers=headers, timeout=self.timeout)
            if resp.status_code < 300:
                return len(batch)
            if resp.status_code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(f"Clay webhook {resp.status_code}: {resp.text[:200]}")
        return 0


@dataclass
class EnrichedPerson:
    account_id: str
    contact_id: str
    email_hash: str
    current_employer: Optional[str]
    current_title: Optional[str]
    linkedin_url: Optional[str]
    employment_start: Optional[str]
    provider: str
    enriched_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def parse_clay_callback(payload: Dict[str, Any]) -> EnrichedPerson:
    """
    Normalize a Clay HTTP-API callback. Clay column names are user-defined; we accept the
    common ones and fall back gracefully. Required: account_id, contact_id (echoed from the push).
    """
    def first(*keys: str) -> Optional[str]:
        for k in keys:
            v = payload.get(k)
            if v not in (None, "", []):
                return str(v)
        return None

    return EnrichedPerson(
        account_id=str(payload["account_id"]),
        contact_id=str(payload["contact_id"]),
        email_hash=str(payload.get("email_hash") or (email_hash(payload["email"]) if payload.get("email") else "")),
        current_employer=first("current_employer", "company_name", "company", "organization", "Current Company"),
        current_title=first("current_title", "title", "job_title", "Job Title", "headline"),
        linkedin_url=first("linkedin_url", "linkedin", "LinkedIn URL"),
        employment_start=first("employment_start", "start_date", "Start Date"),
        provider=first("provider", "source") or "clay",
        enriched_at=first("enriched_at") or datetime.now(timezone.utc).date().isoformat(),
    )


class ClayResultStore:
    """Append-only JSONL store for callbacks; latest row per contact wins."""

    _lock = threading.Lock()   # the orchestrator appends from worker threads

    def __init__(self, path: Path = DEFAULT_STORE):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, person: EnrichedPerson) -> None:
        line = json.dumps(person.to_dict()) + "\n"
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    def latest(self) -> Dict[str, EnrichedPerson]:
        out: Dict[str, EnrichedPerson] = {}
        if not self.path.exists():
            return out
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    p = EnrichedPerson(**json.loads(line))
                    out[p.contact_id] = p
        return out


# ======================================================================================
# Champion-change detection
# ======================================================================================

@dataclass
class ChampionChange:
    contact_id: str
    changed: bool
    change_type: str              # none | left_company | employer_mismatch | title_change_non_buyer | title_change_same_company
    job_change_score: float       # ECRI JobChange term: 1.0 / 0.6 / 0.0
    evidence: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _is_buying_role(title: Optional[str]) -> bool:
    if not title:
        return True  # unknown → don't penalize
    t = title.lower()
    if any(k in t for k in NON_BUYING_ROLE_KEYWORDS):
        return False
    return any(k in t for k in BUYING_ROLE_KEYWORDS) or True


def detect_champion_change(stakeholder: Dict[str, Any], account_name: str, enriched: Optional[EnrichedPerson] = None) -> ChampionChange:
    """
    Order of evidence: explicit CRM left_company_at → enrichment employer mismatch → title change.
    """
    cid = stakeholder["contact_id"]
    if stakeholder.get("left_company_at"):
        return ChampionChange(cid, True, "left_company", 1.0, f"CRM left_company_at={stakeholder['left_company_at']}")

    enr = enriched.to_dict() if enriched else (stakeholder.get("enrichment") or {})
    employer = enr.get("current_employer")
    if employer and normalize_company(employer) and normalize_company(employer) != normalize_company(account_name):
        return ChampionChange(cid, True, "employer_mismatch", 1.0, f"enrichment employer '{employer}' != account '{account_name}'")

    crm_title = (stakeholder.get("title") or "").strip()
    new_title = (enr.get("current_title") or "").strip()
    if crm_title and new_title and normalize_company(crm_title) != normalize_company(new_title):
        if not _is_buying_role(new_title):
            return ChampionChange(cid, True, "title_change_non_buyer", 0.6, f"title '{crm_title}' → '{new_title}' (non-buying role)")
        return ChampionChange(cid, True, "title_change_same_company", 0.0, f"title '{crm_title}' → '{new_title}' (still a buying role; update CRM)")
    return ChampionChange(cid, False, "none", 0.0, "no change detected")


def stale_stakeholders(c360: Dict[str, Any], max_age_days: int = 30) -> List[Dict[str, Any]]:
    as_of = date.fromisoformat(c360["as_of_date"])
    out = []
    for s in c360["relationship"]["stakeholders"]:
        enr = s.get("enrichment")
        if enr is None or enr.get("enrichment_stale"):
            out.append(s)
            continue
        try:
            age = (as_of - date.fromisoformat(enr["enriched_at"])).days
        except Exception:
            age = max_age_days + 1
        if age > max_age_days and (s.get("is_champion") or s.get("is_exec_sponsor") or s.get("persona") == "economic_buyer"):
            out.append(s)
    return out


def enrich_account_stakeholders(c360: Dict[str, Any], store: Optional[ClayResultStore] = None, client: Optional[ClayClient] = None,
                                push_stale: bool = True) -> Dict[str, Any]:
    """
    Merge any Clay results already received into the document, run champion-change detection,
    and (optionally) push still-stale stakeholders to Clay for the next cycle.
    Returns a new document; never mutates the input.
    """
    doc = json.loads(json.dumps(c360))
    store = store or ClayResultStore()
    results = store.latest()
    account_name = doc["account"]["name"]
    changes: List[ChampionChange] = []

    for s in doc["relationship"]["stakeholders"]:
        enriched = results.get(s["contact_id"])
        if enriched:
            s["enrichment"] = {
                "provider": enriched.provider, "enriched_at": enriched.enriched_at,
                "current_employer": enriched.current_employer, "current_title": enriched.current_title,
                "employer_matches_account": normalize_company(enriched.current_employer) == normalize_company(account_name) if enriched.current_employer else None,
                "title_changed": bool(s.get("title") and enriched.current_title and normalize_company(s["title"]) != normalize_company(enriched.current_title)),
                "enrichment_stale": False,
            }
        if s.get("is_champion") or s.get("is_exec_sponsor") or s.get("persona") == "economic_buyer":
            changes.append(detect_champion_change(s, account_name, enriched))

    champ = doc["relationship"]["champion"]
    for ch in changes:
        if ch.changed and ch.job_change_score >= 1.0 and champ.get("contact_id") == ch.contact_id and champ.get("status") != "departed":
            champ["status"] = "departed"
            log.warning("%s: champion %s marked departed (%s)", doc["account"]["account_id"], ch.contact_id, ch.evidence)
    doc["sentiment"].setdefault("ecri_components", {})["job_change"] = max((c.job_change_score for c in changes), default=0.0)
    doc.setdefault("_champion_changes", [c.to_dict() for c in changes])

    if push_stale:
        stale = [s for s in stale_stakeholders(doc) if s["contact_id"] not in results]
        if stale:
            try:
                client = client or ClayClient()
                n = client.push(ClayPushRow(doc["account"]["account_id"], s["contact_id"], s.get("email_hash") or "", s["name"], s.get("title"), account_name) for s in stale)
                log.info("%s: pushed %d stakeholder(s) to Clay", doc["account"]["account_id"], n)
            except ValueError as e:
                log.info("Clay push skipped: %s", e)
    return doc


# ======================================================================================
# CRM adapters
# ======================================================================================

class CRMAdapter(Protocol):
    def find_contact(self, email: str) -> Optional[Dict[str, Any]]: ...
    def upsert_contact(self, contact: Dict[str, Any], external_id: str) -> str: ...
    def update_account_properties(self, account_id: str, props: Dict[str, Any], external_id: str) -> None: ...
    def create_task(self, account_id: str, task: Dict[str, Any], external_id: str) -> str: ...


class HubSpotAdapter:
    """HubSpot CRM v3. Requires a private-app token with crm.objects.{companies,contacts,tasks} read/write."""

    BASE = "https://api.hubapi.com"

    def __init__(self, token: str, timeout: int = 20):
        if requests is None:
            raise RuntimeError("requests required: pip install requests")
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        self.timeout = timeout

    def _req(self, method: str, path: str, **kw) -> Dict[str, Any]:
        for attempt in range(4):
            r = self.s.request(method, f"{self.BASE}{path}", timeout=self.timeout, **kw)
            if r.status_code == 429 and attempt < 3:
                time.sleep(float(r.headers.get("Retry-After", 2 ** attempt)))
                continue
            if r.status_code >= 400:
                raise RuntimeError(f"HubSpot {method} {path} → {r.status_code}: {r.text[:300]}")
            return r.json() if r.text else {}
        raise RuntimeError("HubSpot: retries exhausted")

    def find_contact(self, email: str) -> Optional[Dict[str, Any]]:
        body = {"filterGroups": [{"filters": [{"propertyName": "email", "operator": "EQ", "value": normalize_email(email)}]}],
                "properties": ["email", "firstname", "lastname", "jobtitle", "company", "cse_champion_status"], "limit": 1}
        res = self._req("POST", "/crm/v3/objects/contacts/search", json=body)
        results = res.get("results") or []
        return results[0] if results else None

    def upsert_contact(self, contact: Dict[str, Any], external_id: str) -> str:
        props = {k: v for k, v in contact.items() if k in ("email", "firstname", "lastname", "jobtitle", "company", "cse_persona", "cse_champion_status")}
        props["cse_external_id"] = external_id
        existing = self.find_contact(contact["email"]) if contact.get("email") else None
        if existing:
            self._req("PATCH", f"/crm/v3/objects/contacts/{existing['id']}", json={"properties": props})
            return existing["id"]
        return self._req("POST", "/crm/v3/objects/contacts", json={"properties": props})["id"]

    def update_account_properties(self, account_id: str, props: Dict[str, Any], external_id: str) -> None:
        body = {"properties": {**{k: ("" if v is None else v) for k, v in props.items()}, "cse_external_id": external_id,
                               "cse_last_playbook_at": datetime.now(timezone.utc).strftime("%Y-%m-%d")}}
        self._req("PATCH", f"/crm/v3/objects/companies/{account_id}", json=body)

    def create_task(self, account_id: str, task: Dict[str, Any], external_id: str) -> str:
        # idempotency: search for an existing task with this external id
        search = {"filterGroups": [{"filters": [{"propertyName": "cse_external_id", "operator": "EQ", "value": external_id}]}], "limit": 1}
        try:
            found = self._req("POST", "/crm/v3/objects/tasks/search", json=search).get("results") or []
        except RuntimeError:
            found = []
        due_ms = int((time.time() + 86400 * int(task.get("due_in_days", 2))) * 1000)
        props = {"hs_task_subject": task["title"], "hs_task_body": task.get("body", ""), "hs_task_status": "NOT_STARTED",
                 "hs_task_priority": task.get("priority", "HIGH"), "hs_timestamp": str(due_ms), "cse_external_id": external_id}
        if found:
            self._req("PATCH", f"/crm/v3/objects/tasks/{found[0]['id']}", json={"properties": props})
            return found[0]["id"]
        body = {"properties": props,
                "associations": [{"to": {"id": account_id}, "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 192}]}]}
        return self._req("POST", "/crm/v3/objects/tasks", json=body)["id"]


class SalesforceAdapter:
    """Salesforce REST (v60). Pass an OAuth access token and instance URL from your auth flow."""

    def __init__(self, instance_url: str, access_token: str, api_version: str = "v60.0", timeout: int = 20):
        if requests is None:
            raise RuntimeError("requests required: pip install requests")
        self.base = f"{instance_url.rstrip('/')}/services/data/{api_version}"
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"})
        self.timeout = timeout

    def _req(self, method: str, path: str, **kw) -> Any:
        r = self.s.request(method, f"{self.base}{path}", timeout=self.timeout, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"Salesforce {method} {path} → {r.status_code}: {r.text[:300]}")
        return r.json() if r.text else {}

    def find_contact(self, email: str) -> Optional[Dict[str, Any]]:
        q = f"SELECT Id, Email, Title, AccountId FROM Contact WHERE Email = '{normalize_email(email)}' LIMIT 1"
        recs = self._req("GET", "/query", params={"q": q}).get("records") or []
        return recs[0] if recs else None

    def upsert_contact(self, contact: Dict[str, Any], external_id: str) -> str:
        body = {k: v for k, v in contact.items() if k in ("Email", "FirstName", "LastName", "Title", "AccountId", "CSE_Persona__c", "CSE_Champion_Status__c")}
        res = self._req("PATCH", f"/sobjects/Contact/CSE_External_Id__c/{external_id}", json=body)
        return res.get("id", external_id)

    def update_account_properties(self, account_id: str, props: Dict[str, Any], external_id: str) -> None:
        body = dict(props)
        body["CSE_External_Id__c"] = external_id
        self._req("PATCH", f"/sobjects/Account/{account_id}", json=body)

    def create_task(self, account_id: str, task: Dict[str, Any], external_id: str) -> str:
        due = (datetime.now(timezone.utc).date().toordinal() + int(task.get("due_in_days", 2)))
        body = {"Subject": task["title"], "Description": task.get("body", ""), "WhatId": account_id,
                "ActivityDate": date.fromordinal(due).isoformat(), "Priority": task.get("priority", "High"), "Status": "Not Started"}
        res = self._req("PATCH", f"/sobjects/Task/CSE_External_Id__c/{external_id}", json=body)
        return res.get("id", external_id)


class SlackNotifier:
    def __init__(self, token: str, channel: str, timeout: int = 10):
        if requests is None:
            raise RuntimeError("requests required: pip install requests")
        self.token, self.channel, self.timeout = token, channel, timeout

    def alert(self, text: str) -> None:
        r = requests.post("https://slack.com/api/chat.postMessage",
                          headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
                          json={"channel": self.channel, "text": text, "unfurl_links": False}, timeout=self.timeout)
        data = r.json() if r.text else {}
        if not data.get("ok"):
            log.error("Slack alert failed: %s", data.get("error") or r.status_code)


# ======================================================================================
# CLI
# ======================================================================================

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Clay enrichment and champion-change detection")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("push", help="push stale stakeholders to Clay"); p.add_argument("--input", required=True)
    i = sub.add_parser("ingest", help="ingest a Clay callback payload (JSON object or array)"); i.add_argument("--payload", required=True)
    d = sub.add_parser("detect", help="run champion-change detection on a Customer 360"); d.add_argument("--input", required=True)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if args.cmd == "ingest":
        data = json.loads(Path(args.payload).read_text(encoding="utf-8"))
        store = ClayResultStore()
        rows = data if isinstance(data, list) else [data]
        for row in rows:
            store.append(parse_clay_callback(row))
        print(f"ingested {len(rows)} row(s) into {store.path}")
        return 0

    c360 = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if args.cmd == "push":
        client = ClayClient()
        stale = stale_stakeholders(c360)
        n = client.push(ClayPushRow(c360["account"]["account_id"], s["contact_id"], s.get("email_hash") or "", s["name"], s.get("title"), c360["account"]["name"]) for s in stale)
        print(f"pushed {n} stakeholder(s)")
        return 0
    if args.cmd == "detect":
        doc = enrich_account_stakeholders(c360, push_stale=False)
        print(json.dumps({"champion": doc["relationship"]["champion"], "changes": doc.get("_champion_changes", [])}, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

"""
Call transcript parser → Claude sentiment & risk signals.

Pipeline:  transcript file (Gong JSON / Zoom JSON or VTT / WebVTT / plain "Speaker: text")
           → normalized utterances with speaker role (internal vs customer)
           → PII redaction
           → customer-weighted segments (chunked to ~1,800 tokens)
           → Claude `core.sentiment_analyzer` via forced tool call (`emit_sentiment_analysis`)
           → per-call aggregate: sentiment, urgency, themes, entities, champion-change flag
           → merged into Customer 360 `sentiment.transcript_signals[]`

    python -m src.tools.call_transcript_parser parse --file call.vtt --internal-domains acme.com
    python -m src.tools.call_transcript_parser analyze --file call.vtt --account "Contoso" --segment enterprise
    python -m src.tools.call_transcript_parser analyze --file call.json --offline     # no API; parse + redact only
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

log = logging.getLogger("cse.transcripts")

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SENTIMENT_PROMPT = ROOT / "prompts" / "core" / "sentiment_analyzer.prompt"
SENTIMENT_TOOL = "emit_sentiment_analysis"
APPROX_CHARS_PER_TOKEN = 4
CHUNK_TOKENS = 1800


# ======================================================================================
# Data model
# ======================================================================================

@dataclass
class Utterance:
    speaker: str
    role: str                 # internal | customer | unknown
    start_sec: Optional[float]
    text: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Transcript:
    call_id: str
    occurred_at: Optional[str]
    source_format: str
    utterances: List[Utterance] = field(default_factory=list)
    participants: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def customer_share(self) -> float:
        """Share of transcript characters not attributed to internal speakers (unknown counts as non-internal)."""
        total = sum(len(u.text) for u in self.utterances) or 1
        return sum(len(u.text) for u in self.utterances if u.role != "internal") / total

    def to_dict(self) -> Dict[str, Any]:
        return {"call_id": self.call_id, "occurred_at": self.occurred_at, "source_format": self.source_format,
                "customer_share": round(self.customer_share, 3), "participants": self.participants,
                "utterances": [u.to_dict() for u in self.utterances]}


# ======================================================================================
# PII redaction
# ======================================================================================

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d{1,2}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)")
_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_SSN_RE = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_URL_TOKEN_RE = re.compile(r"(?i)\b(?:api[_-]?key|token|secret|password)\s*[:=]\s*\S+")


def redact_pii(text: str) -> str:
    """Replace emails with stable hashes (joins still work), strip phones, cards, SSNs, and secrets."""
    text = _EMAIL_RE.sub(lambda m: f"[email:{hashlib.sha256(m.group(0).lower().encode()).hexdigest()[:12]}]", text)
    text = _URL_TOKEN_RE.sub("[redacted-secret]", text)
    text = _CARD_RE.sub("[redacted-number]", text)
    text = _SSN_RE.sub("[redacted-id]", text)
    text = _PHONE_RE.sub("[redacted-phone]", text)
    return text


# ======================================================================================
# Parsers
# ======================================================================================

def _role_for(speaker: str, email: Optional[str], internal_domains: Sequence[str], internal_names: Sequence[str]) -> str:
    """
    internal  — email on an internal domain, name in the internal roster, or an [INTERNAL] marker
    customer  — everyone else, *when* we were given any way to recognize internal people
    unknown   — no email and no internal roster/domains supplied at all (caller must tag by hand)
    """
    if email:
        domain = email.lower().rsplit("@", 1)[-1]
        return "internal" if any(domain == d or domain.endswith("." + d) for d in internal_domains) else "customer"
    s = speaker.lower()
    if any(n and n.lower() in s for n in internal_names):
        return "internal"
    if s.startswith("[internal]") or "(internal)" in s:
        return "internal"
    return "customer" if (internal_domains or internal_names) else "unknown"


def _vtt_time_to_sec(ts: str) -> float:
    parts = ts.strip().replace(",", ".").split(":")
    parts = [float(p) for p in parts]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, s = parts
    return h * 3600 + m * 60 + s


def parse_vtt(text: str, call_id: str, internal_domains: Sequence[str] = (), internal_names: Sequence[str] = ()) -> Transcript:
    """WebVTT as exported by Zoom/Teams: cue blocks with optional `<v Speaker>` or `Speaker: text`."""
    t = Transcript(call_id, None, "vtt")
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip())
    for block in blocks:
        lines = [l for l in block.split("\n") if l.strip()]
        if not lines or lines[0].startswith("WEBVTT") or lines[0].startswith("NOTE"):
            continue
        start = None
        body_lines = lines
        for i, l in enumerate(lines):
            if "-->" in l:
                start = _vtt_time_to_sec(l.split("-->")[0])
                body_lines = lines[i + 1:]
                break
        body = " ".join(body_lines).strip()
        if not body:
            continue
        m = re.match(r"<v\s+([^>]+)>(.*)", body)
        if m:
            speaker, said = m.group(1).strip(), re.sub(r"</v>", "", m.group(2)).strip()
        else:
            m2 = re.match(r"([A-Za-z][\w .'\-]{0,60}?):\s+(.*)", body)
            speaker, said = (m2.group(1).strip(), m2.group(2).strip()) if m2 else ("unknown", body)
        t.utterances.append(Utterance(speaker, _role_for(speaker, None, internal_domains, internal_names), start, said))
    return t


def parse_gong_json(data: Dict[str, Any], internal_domains: Sequence[str] = (), internal_names: Sequence[str] = ()) -> Transcript:
    """
    Gong `calls/transcript` + `calls/extensive` shapes. Expected keys (any subset):
      callId, started, parties[{speakerId, name, emailAddress, affiliation}], transcript[{speakerId, sentences[{start, text}]}]
    """
    call_id = str(data.get("callId") or data.get("id") or "gong")
    started = data.get("started") or data.get("scheduled")
    parties = {str(p.get("speakerId") or p.get("id")): p for p in data.get("parties", [])}
    t = Transcript(call_id, started[:10] if started else None, "gong",
                   participants=[{"name": p.get("name"), "email_hash": hashlib.sha256(p["emailAddress"].lower().encode()).hexdigest() if p.get("emailAddress") else None,
                                  "affiliation": p.get("affiliation")} for p in parties.values()])
    for seg in data.get("transcript", []):
        sid = str(seg.get("speakerId"))
        party = parties.get(sid, {})
        speaker = party.get("name") or f"speaker_{sid}"
        aff = (party.get("affiliation") or "").lower()
        if aff in ("internal", "company"):
            role = "internal"
        elif aff in ("external", "customer"):
            role = "customer"
        else:
            role = _role_for(speaker, party.get("emailAddress"), internal_domains, internal_names)
        for s in seg.get("sentences", []):
            if s.get("text"):
                t.utterances.append(Utterance(speaker, role, (s.get("start") or 0) / 1000.0 if s.get("start") else None, s["text"]))
    return t


def parse_zoom_json(data: Dict[str, Any], internal_domains: Sequence[str] = (), internal_names: Sequence[str] = ()) -> Transcript:
    """Zoom recording transcript JSON: {meeting_id, start_time, participants[], transcript:[{speaker, email?, start_time, text}]}."""
    call_id = str(data.get("meeting_id") or data.get("uuid") or "zoom")
    started = data.get("start_time")
    t = Transcript(call_id, started[:10] if started else None, "zoom",
                   participants=[{"name": p.get("name") or p.get("user_name"), "email_hash": hashlib.sha256(p["user_email"].lower().encode()).hexdigest() if p.get("user_email") else None}
                                 for p in data.get("participants", [])])
    emails = {(p.get("name") or p.get("user_name")): p.get("user_email") for p in data.get("participants", [])}
    for row in data.get("transcript", []):
        speaker = row.get("speaker") or row.get("user_name") or "unknown"
        email = row.get("email") or emails.get(speaker)
        st = row.get("start_time")
        start = _vtt_time_to_sec(st) if isinstance(st, str) and ":" in st else (float(st) if st is not None else None)
        if row.get("text"):
            t.utterances.append(Utterance(speaker, _role_for(speaker, email, internal_domains, internal_names), start, row["text"]))
    return t


def parse_plain(text: str, call_id: str, internal_domains: Sequence[str] = (), internal_names: Sequence[str] = ()) -> Transcript:
    """`Speaker: text` lines, with optional `[INTERNAL]` prefix and optional `[mm:ss]` stamps."""
    t = Transcript(call_id, None, "plain")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        start = None
        m = re.match(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*(.*)", line)
        if m:
            start, line = _vtt_time_to_sec(m.group(1)), m.group(2)
        m2 = re.match(r"(\[INTERNAL\]\s*)?([A-Za-z][\w .'\-]{0,60}?):\s+(.*)", line)
        if not m2:
            if t.utterances:
                t.utterances[-1].text += " " + line
            continue
        prefix, speaker, said = m2.group(1), m2.group(2).strip(), m2.group(3).strip()
        role = "internal" if prefix else _role_for(speaker, None, internal_domains, internal_names)
        t.utterances.append(Utterance(speaker, role, start, said))
    return t


def load_transcript(path: Path, internal_domains: Sequence[str] = (), internal_names: Sequence[str] = ()) -> Transcript:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".json":
        data = json.loads(raw)
        if "transcript" in data and ("parties" in data or "callId" in data):
            return parse_gong_json(data, internal_domains, internal_names)
        if "transcript" in data:
            return parse_zoom_json(data, internal_domains, internal_names)
        raise ValueError(f"{path}: unrecognized transcript JSON shape")
    if path.suffix.lower() in (".vtt", ".srt") or raw.lstrip().startswith("WEBVTT"):
        return parse_vtt(raw, path.stem, internal_domains, internal_names)
    return parse_plain(raw, path.stem, internal_domains, internal_names)


# ======================================================================================
# Chunking
# ======================================================================================

def redact_transcript(t: Transcript) -> Transcript:
    for u in t.utterances:
        u.text = redact_pii(u.text)
    return t


def render_for_prompt(utterances: Iterable[Utterance]) -> str:
    lines = []
    for u in utterances:
        tag = "[INTERNAL] " if u.role == "internal" else ("" if u.role == "customer" else "[UNKNOWN] ")
        lines.append(f"{tag}{u.speaker}: {u.text}")
    return "\n".join(lines)


def chunk_transcript(t: Transcript, max_tokens: int = CHUNK_TOKENS) -> List[List[Utterance]]:
    """Greedy chunks by approximate token count, never splitting an utterance; keeps internal context."""
    chunks: List[List[Utterance]] = []
    cur: List[Utterance] = []
    size = 0
    for u in t.utterances:
        n = max(1, len(u.text) // APPROX_CHARS_PER_TOKEN) + 8
        if cur and size + n > max_tokens:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(u)
        size += n
    if cur:
        chunks.append(cur)
    # drop chunks with no customer speech at all — nothing to analyze
    return [c for c in chunks if any(u.role != "internal" for u in c)] or chunks[:1]


# ======================================================================================
# Claude analysis
# ======================================================================================

_SCHEMA_RE = re.compile(r"<output_format>.*?(\{.*\})\s*</output_format>", re.DOTALL)


def load_sentiment_prompt() -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
    """Return (body, header, embedded tool input_schema) from the sentiment_analyzer prompt file."""
    from src.prompts import parse_prompt_file
    prompt = parse_prompt_file(SENTIMENT_PROMPT)
    header = {"model": prompt.model, "max_tokens": prompt.max_tokens, "temperature": prompt.temperature, "inputs": prompt.inputs}
    sm = _SCHEMA_RE.search(prompt.body)
    if not sm:
        raise ValueError("sentiment_analyzer.prompt: embedded schema not found")
    return prompt.body, header, json.loads(sm.group(1))


def analyze_segment_with_claude(segment_text: str, account_name: str, segment: str, source_type: str,
                                today: Optional[str] = None, client: Any = None) -> Dict[str, Any]:
    import anthropic
    client = client or anthropic.Anthropic()
    body, header, schema = load_sentiment_prompt()
    rendered = (body.replace("{{account_name}}", account_name).replace("{{segment}}", segment)
                .replace("{{source_type}}", source_type).replace("{{today}}", today or date.today().isoformat()))
    model = header.get("model") or os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5")
    resp = client.messages.create(
        model=model, max_tokens=int(header["max_tokens"]), temperature=float(header["temperature"]),
        system=[{"type": "text", "text": rendered, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": f"<untrusted_customer_text>\n{segment_text}\n</untrusted_customer_text>"}],
        tools=[{"name": SENTIMENT_TOOL, "description": "Emit the structured sentiment analysis for this text.", "input_schema": schema}],
        tool_choice={"type": "tool", "name": SENTIMENT_TOOL},
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and block.name == SENTIMENT_TOOL:
            out = dict(block.input)
            try:
                import jsonschema
                jsonschema.Draft202012Validator(schema).validate(out)
            except ImportError:
                pass
            return out
    raise RuntimeError("sentiment analyzer did not emit a tool call")


def aggregate_segments(call_id: str, occurred_at: Optional[str], results: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Collapse per-chunk analyses into the Customer 360 `transcript_signals[]` shape."""
    if not results:
        return {"call_id": call_id, "occurred_at": occurred_at, "sentiment": 0.0, "urgency": "none", "themes": [], "entities": [],
                "champion_change_detected": False, "summary": "no analyzable customer speech"}
    order = ["none", "low", "medium", "high", "critical"]
    weights = [max(0.2, r.get("confidence", 0.5)) for r in results]
    sentiment = sum(r["sentiment"] * w for r, w in zip(results, weights)) / sum(weights)
    urgency = max((r.get("urgency", "none") for r in results), key=order.index)
    themes: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for r in results:
        for th in r.get("themes", []):
            key = (th["theme"], th["polarity"])
            if key not in themes or order.index(th.get("urgency", "none")) > order.index(themes[key].get("urgency", "none")):
                themes[key] = th
    entities: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for r in results:
        for e in r.get("entities", []):
            entities.setdefault((e["type"], e["value"].lower()), e)
    champion = any(r.get("champion_change_detected") or any(t["theme"] == "champion_change" for t in r.get("themes", [])) for r in results)
    summary = " ".join(r.get("summary", "") for r in results)[:400]
    return {
        "call_id": call_id, "occurred_at": occurred_at or date.today().isoformat(),
        "sentiment": round(sentiment, 2), "urgency": urgency,
        "themes": sorted(themes.values(), key=lambda t: -order.index(t.get("urgency", "none")))[:8],
        "entities": list(entities.values())[:20], "champion_change_detected": champion, "summary": summary,
    }


def analyze_transcript(t: Transcript, account_name: str, segment: str, offline: bool = False, client: Any = None) -> Dict[str, Any]:
    t = redact_transcript(t)
    chunks = chunk_transcript(t)
    if offline:
        signal = aggregate_segments(t.call_id, t.occurred_at, [])
        signal["summary"] = f"offline: parsed {len(t.utterances)} utterances ({t.customer_share:.0%} customer speech) in {len(chunks)} chunk(s); no Claude analysis"
        return signal
    results = [analyze_segment_with_claude(render_for_prompt(c), account_name, segment, "call_transcript_segment", client=client) for c in chunks]
    return aggregate_segments(t.call_id, t.occurred_at, results)


def resolve_transcript_uri(uri: str) -> Path:
    """Local paths and file:// URIs are supported directly; object-store URIs are expected to be staged locally first."""
    if uri.startswith("file://"):
        return Path(uri[len("file://"):])
    p = Path(uri)
    if p.exists():
        return p
    staged = ROOT / "feeds" / "transcripts" / Path(uri).name
    if staged.exists():
        return staged
    raise FileNotFoundError(f"transcript not available locally: {uri} (stage it under feeds/transcripts/)")


def parse_and_analyze_pending(c360: Dict[str, Any], offline: bool = False, internal_domains: Sequence[str] = ()) -> Dict[str, Any]:
    """For each conversations[] entry with a transcript_uri and parsed=false, analyze and merge into sentiment.transcript_signals[]."""
    doc = json.loads(json.dumps(c360))
    internal_domains = tuple(internal_domains) or tuple(d for d in os.environ.get("CSE_INTERNAL_DOMAINS", "").split(",") if d)
    internal_names = tuple(m.get("name") for m in doc["account"].get("team", []) if m.get("name"))
    signals = doc["sentiment"].setdefault("transcript_signals", [])
    known = {s["call_id"] for s in signals}
    for conv in doc.get("conversations", []):
        if conv.get("parsed") or not conv.get("transcript_uri") or conv["call_id"] in known:
            continue
        try:
            t = load_transcript(resolve_transcript_uri(conv["transcript_uri"]), internal_domains, internal_names)
            t.call_id, t.occurred_at = conv["call_id"], conv.get("occurred_at") or t.occurred_at
            signals.append(analyze_transcript(t, doc["account"]["name"], doc["account"]["segment"], offline=offline))
            conv["parsed"] = True
        except Exception as e:
            log.error("%s: transcript %s failed: %s", doc["account"]["account_id"], conv["call_id"], e)
    customer_sents = [s["sentiment"] for s in signals if s.get("occurred_at") and (date.fromisoformat(doc["as_of_date"]) - date.fromisoformat(s["occurred_at"])).days <= 30]
    if customer_sents:
        doc["sentiment"]["transcript_sentiment_30d"] = round(sum(customer_sents) / len(customer_sents), 2)
    return doc


# ======================================================================================
# CLI
# ======================================================================================

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Parse and analyze call transcripts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("parse", "analyze"):
        p = sub.add_parser(name)
        p.add_argument("--file", required=True)
        p.add_argument("--internal-domains", default=os.environ.get("CSE_INTERNAL_DOMAINS", ""))
        p.add_argument("--internal-names", default="")
        if name == "analyze":
            p.add_argument("--account", default="the account")
            p.add_argument("--segment", default="mid_market")
            p.add_argument("--offline", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    domains = [d.strip() for d in args.internal_domains.split(",") if d.strip()]
    names = [n.strip() for n in args.internal_names.split(",") if n.strip()]
    t = load_transcript(Path(args.file), domains, names)
    if args.cmd == "parse":
        print(json.dumps(redact_transcript(t).to_dict(), indent=2))
        return 0
    print(json.dumps(analyze_transcript(t, args.account, args.segment, offline=args.offline), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

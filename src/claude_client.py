"""
Claude client for the orchestrator.

- Cached prefix: system prompt + playbook prompt body both carry cache_control, so across a
  book only the Customer 360 view and the instruction are billed as fresh input.
- Per-prompt tool schema: the PlaybookAction schema minus the sub-objects this prompt does not
  own (~55% smaller for most prompts; fewer constrained-decoding retries).
- Prior-prompt outputs travel in the user turn (<prior_outputs>), never in the body.
- Truncation-safe: a `max_tokens` stop never yields a partial object; it retries once with
  headroom and a tightening instruction.
- One validation retry with the errors fed back as a tool_result; on a second failure the
  attempts are raised for the orchestrator to write to `_invalid/` for manual review.
- Batch mode for nightly server runs (Messages Batches API: half price, no rate-limit tuning).
"""

from __future__ import annotations

import copy
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.prompts import Prompt, PromptRegistry
from src.validation import validate_action

log = logging.getLogger("cse.claude")

TOOL_NAME = "emit_playbook_action"
TOOL_DESCRIPTION = (
    "Emit the single PlaybookAction for this account and instruction. It must validate against the provided "
    "schema. Every factual or numeric claim needs an evidence[] entry whose source_path resolves in the "
    "<customer_360> block and whose value matches what the document says there."
)

ALL_SUBOBJECTS = ["renewal_plan", "onboarding_plan", "feature_audit", "expansion_brief", "ebr"]
OWNED_SUBOBJECTS: Dict[str, List[str]] = {
    "retention.churn_risk_rca": [],
    "retention.renewal_defense_playbook": ["renewal_plan"],
    "adoption.ttv_acceleration": ["onboarding_plan"],
    "adoption.feature_depth_audit": ["feature_audit"],
    "expansion.whitespace_expansion_finder": ["expansion_brief"],
    "expansion.executive_ebr_generator": ["ebr"],
}
TRUNCATION_HEADROOM = 1.5
MAX_TRUNCATION_RETRIES = 1
RETRYABLE_STATUS = (429, 529, 500, 502, 503)


def schema_for(prompt_id: str, base_schema: Dict[str, Any]) -> Dict[str, Any]:
    """The base PlaybookAction schema with only the optional sub-objects this prompt owns."""
    s = copy.deepcopy(base_schema)
    keep = set(OWNED_SUBOBJECTS.get(prompt_id, ALL_SUBOBJECTS))
    for name in ALL_SUBOBJECTS:
        if name not in keep:
            s["properties"].pop(name, None)
    return s


class InvalidOutputError(ValueError):
    def __init__(self, prompt_id: str, attempts: List[Dict[str, Any]]):
        super().__init__(f"{prompt_id}: output invalid after {len(attempts)} attempt(s): {attempts[-1].get('errors', [])[:3]}")
        self.prompt_id = prompt_id
        self.attempts = attempts


@dataclass
class ClaudeCallResult:
    action: Dict[str, Any]
    model: str
    request_id: Optional[str]
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    latency_s: float
    retries: int
    stop_reason: str = "tool_use"
    invalid_attempts: List[Dict[str, Any]] = field(default_factory=list)


def build_user_turn(c360_view: Dict[str, Any], prior_outputs: Dict[str, Any], instruction: str) -> str:
    parts = [f"<customer_360>\n{json.dumps(c360_view, ensure_ascii=False, default=str)}\n</customer_360>"]
    if prior_outputs:
        parts.append(f"<prior_outputs>\n{json.dumps(prior_outputs, ensure_ascii=False, default=str)}\n</prior_outputs>")
    parts.append(f"<instruction>{instruction}</instruction>")
    return "\n".join(parts)


class ClaudeEmitter:
    def __init__(self, registry: PromptRegistry, base_schema: Dict[str, Any], system_prompt: str, max_retries: int = 1, client: Any = None):
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        self.client = client
        self.registry = registry
        self.base_schema = base_schema
        self.system_prompt = system_prompt
        self.max_retries = max_retries

    # ---- request construction ---------------------------------------------------------

    def build_request(self, prompt: Prompt, body: str, schema: Dict[str, Any], messages: List[Dict[str, Any]], max_tokens: int) -> Dict[str, Any]:
        system = [{"type": "text", "text": self.system_prompt, "cache_control": {"type": "ephemeral"}}]
        body_block: Dict[str, Any] = {"type": "text", "text": body}
        if "body" in prompt.cache:
            body_block["cache_control"] = {"type": "ephemeral"}
        system.append(body_block)
        return dict(
            model=prompt.model,
            max_tokens=max_tokens,
            temperature=prompt.temperature,
            system=system,
            messages=messages,
            tools=[{"name": TOOL_NAME, "description": TOOL_DESCRIPTION, "input_schema": schema}],
            tool_choice={"type": "tool", "name": TOOL_NAME},
        )

    # ---- synchronous path ---------------------------------------------------------------

    def emit(self, prompt_id: str, static_vars: Dict[str, Any], c360_view: Dict[str, Any], prior_outputs: Dict[str, Any],
             instruction: str) -> ClaudeCallResult:
        prompt = self.registry.get(prompt_id)
        body = prompt.render(static_vars)
        schema = schema_for(prompt_id, self.base_schema)
        messages: List[Dict[str, Any]] = [{"role": "user", "content": build_user_turn(c360_view, prior_outputs, instruction)}]
        max_tokens = prompt.max_tokens
        t0 = time.time()
        retries = 0              # validation retries (budget: max_retries)
        truncation_retries = 0   # budget: MAX_TRUNCATION_RETRIES, counted separately
        invalid: List[Dict[str, Any]] = []

        while True:
            resp = self._call(prompt, body, schema, messages, max_tokens)
            blocks = [b for b in resp.content if getattr(b, "type", None) == "tool_use" and getattr(b, "name", None) == TOOL_NAME]
            truncated = getattr(resp, "stop_reason", None) == "max_tokens"
            if truncated or not blocks:
                errors = [
                    f"output {'was truncated at ' + str(max_tokens) + ' tokens' if truncated else 'did not call ' + TOOL_NAME}; "
                    "shorten diagnosis.summary, talk_track and communication bodies to their minimum and re-emit the COMPLETE object"
                ]
                invalid.append({"attempt": len(invalid) + 1, "errors": errors, "partial": dict(getattr(blocks[0], "input", {}) or {}) if blocks else None})
                if truncation_retries >= MAX_TRUNCATION_RETRIES:
                    raise InvalidOutputError(prompt_id, invalid)
                truncation_retries += 1
                max_tokens = int(max_tokens * TRUNCATION_HEADROOM)
                messages = [{"role": "user", "content": build_user_turn(c360_view, prior_outputs, instruction + " " + errors[0])}]
                continue
            else:
                action = dict(blocks[0].input)
                errors = validate_action(action, c360_view, schema)
                if not errors:
                    u = resp.usage
                    return ClaudeCallResult(
                        action=action, model=resp.model, request_id=getattr(resp, "_request_id", None),
                        input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                        cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
                        cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
                        latency_s=time.time() - t0, retries=retries + truncation_retries, stop_reason=resp.stop_reason, invalid_attempts=invalid,
                    )
                invalid.append({"attempt": len(invalid) + 1, "errors": errors, "action": action})

            if retries >= self.max_retries:
                raise InvalidOutputError(prompt_id, invalid)
            retries += 1
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": blocks[0].id, "is_error": True,
                "content": "Your previous output failed validation:\n- " + "\n- ".join(errors[:10]) +
                           f"\nFix every error and call {TOOL_NAME} again with the corrected object.",
            }]})

    def _call(self, prompt: Prompt, body: str, schema: Dict[str, Any], messages: List[Dict[str, Any]], max_tokens: int):
        import anthropic
        backoff = 2.0
        for attempt in range(6):
            try:
                return self.client.messages.create(**self.build_request(prompt, body, schema, messages, max_tokens))
            except (anthropic.RateLimitError, anthropic.APIStatusError) as e:
                status = getattr(e, "status_code", None)
                if status in RETRYABLE_STATUS and attempt < 5:
                    sleep = backoff * (1 + 0.25 * (attempt % 3))
                    log.warning("Anthropic %s; retrying in %.1fs", status, sleep)
                    time.sleep(sleep)
                    backoff *= 2
                    continue
                raise
        raise RuntimeError("unreachable")

    # ---- batch path (nightly) -----------------------------------------------------------

    def submit_batch(self, items: List[Dict[str, Any]]) -> str:
        """
        items: [{custom_id, prompt_id, static_vars, c360_view, prior_outputs, instruction}]
        Returns the batch id. Results are collected with `collect_batch`; validation happens there.
        """
        requests = []
        for it in items:
            p = self.registry.get(it["prompt_id"])
            body = p.render(it["static_vars"])
            msgs = [{"role": "user", "content": build_user_turn(it["c360_view"], it.get("prior_outputs") or {}, it["instruction"])}]
            requests.append({"custom_id": it["custom_id"], "params": self.build_request(p, body, schema_for(it["prompt_id"], self.base_schema), msgs, p.max_tokens)})
        return self.client.messages.batches.create(requests=requests).id

    def collect_batch(self, batch_id: str, poll_s: int = 30, timeout_s: int = 24 * 3600) -> Dict[str, Any]:
        """Poll until the batch ends; return {custom_id: result} (succeeded results carry `.message`)."""
        start = time.time()
        while True:
            b = self.client.messages.batches.retrieve(batch_id)
            if b.processing_status == "ended":
                break
            if time.time() - start > timeout_s:
                raise TimeoutError(f"batch {batch_id} did not end within {timeout_s}s")
            time.sleep(poll_s)
        return {r.custom_id: r.result for r in self.client.messages.batches.results(batch_id)}

    def action_from_batch_result(self, prompt_id: str, result: Any, c360_view: Dict[str, Any]) -> Dict[str, Any]:
        """Validate one batch result; raises InvalidOutputError on failure (no retry in batch mode)."""
        if getattr(result, "type", None) != "succeeded":
            raise InvalidOutputError(prompt_id, [{"attempt": 1, "errors": [f"batch result type {getattr(result, 'type', '?')}"]}])
        msg = result.message
        blocks = [b for b in msg.content if getattr(b, "type", None) == "tool_use" and b.name == TOOL_NAME]
        if msg.stop_reason == "max_tokens" or not blocks:
            raise InvalidOutputError(prompt_id, [{"attempt": 1, "errors": ["truncated or missing tool call in batch result"]}])
        action = dict(blocks[0].input)
        errors = validate_action(action, c360_view, schema_for(prompt_id, self.base_schema))
        if errors:
            raise InvalidOutputError(prompt_id, [{"attempt": 1, "errors": errors, "action": action}])
        return action

"""
Prompt registry: loads `prompts/**/*.prompt` files (YAML header + XML body), renders static
variables, and declares each prompt's inputs so the orchestrator can resolve them generically.

Header format (YAML, between `---` fences):

    id: retention.churn_risk_rca
    version: 2.4.0
    model: claude-sonnet-5-5
    temperature: 0.2
    max_tokens: 4096
    inputs:                       # variable → source spec, resolved by the orchestrator
      segment_benchmarks_json: c360:benchmarks
      today: run:today
      feature_catalog_json: c360:_feature_catalog|catalog:feature_catalog
    cache: [system, body]
    description: one plain-English line

Source specs:
    run:<key>        a run-level value (today, variant, playbook_id, csm_name)
    c360:<path>      a dotted path into the Customer 360 (missing → next alternative)
    catalog:<name>   a default catalog from src/catalogs.py
    text:<literal>   a literal string
Alternatives are separated by `|` and tried left to right; `{}` and `[]` are accepted literals.

Prior-prompt outputs are NOT variables: the client puts them in the user turn as <prior_outputs>
so the rendered body stays identical across accounts and is served from the prompt cache.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

import yaml

ROOT = Path(__file__).resolve().parents[1]
PROMPT_DIR = ROOT / "prompts"
_HEADER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
_PLACEHOLDER_RE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


@dataclass
class Prompt:
    id: str
    version: str
    model: str
    temperature: float
    max_tokens: int
    inputs: Dict[str, str]
    description: str
    body: str
    path: Path
    cache: List[str] = field(default_factory=lambda: ["system", "body"])

    @property
    def variables(self) -> List[str]:
        return list(self.inputs.keys())

    def render(self, variables: Dict[str, Any]) -> str:
        missing = [v for v in self.inputs if v not in variables]
        if missing:
            raise KeyError(f"Prompt {self.id} missing variables: {missing}")
        text = self.body
        for name, value in variables.items():
            rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
            text = text.replace("{{" + name + "}}", rendered)
        leftover = sorted(set(_PLACEHOLDER_RE.findall(text)))
        if leftover:
            raise KeyError(f"Prompt {self.id} has unrendered placeholders: {leftover}")
        return text


def parse_prompt_file(path: Path, default_model: str = "claude-sonnet-5-5") -> Prompt:
    text = path.read_text(encoding="utf-8")
    m = _HEADER_RE.match(text)
    if not m:
        raise ValueError(f"{path}: missing YAML header")
    header = yaml.safe_load(m.group(1)) or {}
    if "id" not in header:
        raise ValueError(f"{path}: header has no id")
    inputs = header.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise ValueError(f"{path}: `inputs` must be a mapping of variable → source spec")
    body = m.group(2).strip()
    declared = set(inputs)
    used = set(_PLACEHOLDER_RE.findall(body))
    undeclared = sorted(used - declared)
    if undeclared:
        raise ValueError(f"{path}: body uses undeclared variables {undeclared}; declare them under `inputs:`")
    return Prompt(
        id=str(header["id"]),
        version=str(header.get("version", "0.0.0")),
        model=str(header.get("model", default_model)),
        temperature=float(header.get("temperature", 0.2)),
        max_tokens=int(header.get("max_tokens", 4096)),
        inputs={str(k): str(v) for k, v in inputs.items()},
        description=str(header.get("description", "")).strip(),
        body=body,
        path=path,
        cache=list(header.get("cache") or ["system", "body"]),
    )


class PromptRegistry:
    def __init__(self, prompt_dir: Path = PROMPT_DIR, default_model: str = "claude-sonnet-5-5"):
        self.prompts: Dict[str, Prompt] = {}
        for p in sorted(prompt_dir.rglob("*.prompt")):
            prompt = parse_prompt_file(p, default_model)
            if prompt.id in self.prompts:
                raise ValueError(f"duplicate prompt id {prompt.id}: {p} and {self.prompts[prompt.id].path}")
            self.prompts[prompt.id] = prompt

    def get(self, prompt_id: str) -> Prompt:
        if prompt_id not in self.prompts:
            raise KeyError(f"Unknown prompt id {prompt_id}; have {sorted(self.prompts)}")
        return self.prompts[prompt_id]

    def __len__(self) -> int:
        return len(self.prompts)

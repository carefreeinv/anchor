"""Shared client for the Anchor fleet: endpoint registry + model-quirk handling.

Every endpoint is OpenAI-compatible. Quirks are applied here so callers stay
model-agnostic. Supported quirk keys (set per endpoint in endpoints.yaml):

  system_role: fold_into_user   no system slot (Gemma 3) or system prompt discouraged
                                (DeepSeek-R1 distills) — system text folds into the
                                first user turn
  think_toggle: qwen3|nemotron  hybrid-reasoning switch (/think suffix vs
                                'detailed thinking on/off' system line)
  strip_think: true             remove <think>...</think> from output (implied by
                                think_toggle)
  system_suffix: <line>         per-model guardrail appended to the system text
                                (Gemma's BLOCKED rule, R1's LOW-CONFIDENCE rule)
  temperature / temperature_thinking      default sampling override per mode
                                (e.g. Mistral 0.15; Nemotron thinking-off 0)
  sampling / sampling_thinking: {...}     extra sampling params merged into the
                                request (top_p, top_k, ...); temperature wins
  max_context: <n>              serving context ceiling; completion tokens are
                                capped to it
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY = Path(__file__).resolve().parent / "endpoints.yaml"
THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)

MAX_RETRIES = 2  # matches the Anchor stop condition elsewhere: retry twice, then surface the failure
RETRY_BACKOFF_SECONDS = 1.0


def _post_with_retry(url: str, *, json: dict, headers: dict, timeout: int) -> requests.Response:
    """POST with a couple of short retries for transient connection errors / 5xx.

    The swarm tier in particular is CPU-bound and flaky under load, so a bare
    single-shot request is too brittle to trust.
    """
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.post(url, json=json, headers=headers, timeout=timeout)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_exc = exc
        else:
            if resp.status_code < 500:
                return resp
            last_exc = requests.exceptions.HTTPError(f"{resp.status_code} from {url}", response=resp)
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    raise last_exc


@dataclass
class Endpoint:
    name: str
    tier: str
    base_url: str
    model: str
    quirks: dict = field(default_factory=dict)

    def chat(self, messages: list[dict], *, thinking: bool = False,
             temperature: float | None = None, max_tokens: int = 4096,
             timeout: int = 600) -> str:
        msgs = [dict(m) for m in messages]

        # Registry-driven guardrail line(s) a model needs to behave (Gemma's BLOCKED
        # rule, R1's LOW-CONFIDENCE budget rule, ...). Applied before any folding so
        # the guardrail rides along whatever the template quirks do next.
        suffix = self.quirks.get("system_suffix")
        if suffix:
            for m in msgs:
                if m["role"] == "system":
                    m["content"] += "\n" + suffix
                    break
            else:
                msgs.insert(0, {"role": "system", "content": suffix})

        # Gemma-style: no system role — fold system text into first user turn.
        # (Also DeepSeek-R1 distills: official guidance is no system prompt at all.)
        if self.quirks.get("system_role") == "fold_into_user":
            sys_parts = [m["content"] for m in msgs if m["role"] == "system"]
            msgs = [m for m in msgs if m["role"] != "system"]
            if sys_parts and msgs:
                msgs[0]["content"] = "\n\n---\n\n".join(sys_parts + [msgs[0]["content"]])

        # Thinking toggles.
        toggle = self.quirks.get("think_toggle")
        if toggle == "qwen3" and msgs:
            msgs[-1]["content"] += " /think" if thinking else " /no_think"
        elif toggle == "nemotron":
            line = f"detailed thinking {'on' if thinking else 'off'}"
            if msgs and msgs[0]["role"] == "system":
                msgs[0]["content"] = f"{line}\n{msgs[0]['content']}"
            else:
                msgs.insert(0, {"role": "system", "content": line})

        # Sampling: caller-explicit > per-endpoint quirk > Anchor defaults.
        if temperature is None:
            temperature = self.quirks.get(
                "temperature_thinking" if thinking else "temperature",
                0.6 if thinking else 0.2)
        # Never greedy while thinking — Qwen3 and the R1 distills both document
        # repetition loops under greedy decoding in reasoning mode.
        if thinking and temperature <= 0:
            temperature = 0.6

        # An endpoint's max_context is a hard serving ceiling; never request a
        # completion larger than the context that has to hold it.
        ceiling = self.quirks.get("max_context")
        if ceiling:
            max_tokens = min(max_tokens, int(ceiling))

        headers = {}
        api_key = os.environ.get("ANCHOR_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {"model": self.model, "messages": msgs,
                   "temperature": temperature, "max_tokens": max_tokens}
        # Extra per-endpoint sampling params (top_p, top_k, ...), e.g. Qwen3 thinking
        # wants top_p 0.95 / top_k 20. The resolved temperature above always wins.
        extra = self.quirks.get("sampling_thinking" if thinking else "sampling")
        if extra:
            payload = {**extra, **payload}

        resp = _post_with_retry(
            f"{self.base_url.rstrip('/')}/chat/completions",
            json=payload,
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"] or ""
        if self.quirks.get("strip_think") or toggle:
            text = THINK_RE.sub("", text)
        return text.strip()


class Fleet:
    def __init__(self, registry_path: str | Path = DEFAULT_REGISTRY):
        data = yaml.safe_load(Path(registry_path).read_text(encoding="utf-8"))
        self.endpoints = [Endpoint(**e) for e in data.get("endpoints", [])]
        self.roles: dict[str, list[str]] = data.get("roles", {})
        self._rr: dict[str, int] = {}

    def by_tier(self, tier: str) -> list[Endpoint]:
        return [e for e in self.endpoints if e.tier == tier]

    def pick(self, role: str) -> Endpoint:
        """First healthy-tier endpoint for a role, round-robin within the tier."""
        for tier in self.roles.get(role, []):
            candidates = self.by_tier(tier)
            if candidates:
                i = self._rr.get(tier, 0)
                self._rr[tier] = (i + 1) % len(candidates)
                return candidates[i % len(candidates)]
        raise LookupError(f"No endpoint available for role '{role}' "
                          f"(tiers tried: {self.roles.get(role)})")


def load_prompt(rel: str) -> str:
    """Load a prompt/template from the repo, e.g. 'anchor/system-prompts/mythos-core.md'."""
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


REQUIRED_FOOTER = ("## Result", "## How to verify")


def has_required_footer(text: str) -> bool:
    return all(h in text for h in REQUIRED_FOOTER)

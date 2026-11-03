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
  min_completion_tokens: <n>    floor for max_tokens (thinking locals often burn
                                a small budget on reasoning and leave content="")
  openai_think: true|false      Ollama opt-in only — when the key is present,
                                send OpenAI-body `think` matching thinking=.
                                On HTTP 400, drop the field and cache on the
                                Endpoint so later calls skip re-probing
  reasoning_effort: low|medium|high|xhigh
                                Grok-family dial; sent as reasoning_effort on
                                the OpenAI-compatible request body

Endpoints also carry an optional top-level ``local: true|false`` (not a quirk) —
whether this endpoint runs on hardware the operator powers. It is what the site
inference-load governor caps (see ``inference_load.py``); when unset, locality is
inferred from the base URL. Cloud tiers are never local, so a load policy can
never silently block them.
"""
from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests
import yaml

try:
    from inference_load import endpoint_is_local
except ImportError:  # standalone copy of this file, without the load governor
    endpoint_is_local = None


class EmptyAssistantText(RuntimeError):
    """HTTP 200 but no usable assistant ``content`` (silent empty string).

    Thinking locals (Qwen3 via Ollama) sometimes put tokens only in
    ``message.reasoning`` / burn ``max_tokens`` on thinking. Callers must not
    treat that as a successful empty reply — raise instead of returning "".
    """


def project_root_from(start: Path | None = None) -> Path:
    """Resolve the project (or Anchor) root from a scripts/MCP file path.

    Supports:
    - source tree: ``<root>/scripts/*.py``, ``<root>/mcp/<name>/server.py``
    - scaffold: ``<root>/.anchor/scripts/*.py``, ``<root>/.anchor/mcp/<name>/server.py``
    """
    p = (start or Path(__file__)).resolve()
    if p.is_file():
        p = p.parent
    # .anchor/scripts → project root
    if p.name == "scripts" and p.parent.name == ".anchor":
        return p.parent.parent
    # .anchor/mcp/<server> → project root
    if p.parent.name == "mcp" and p.parent.parent.name == ".anchor":
        return p.parent.parent.parent
    # source / legacy: scripts/ → root
    if p.name == "scripts":
        return p.parent
    # source / legacy: mcp/<server> → root
    if p.parent.name == "mcp":
        return p.parent.parent
    # walk for markers
    for cur in [p, *p.parents]:
        if cur.name == ".anchor":
            return cur.parent
        if (cur / ".plans").is_dir() or (cur / ".anchor-manifest.json").is_file():
            return cur
        if (cur / "anchor" / "ANCHOR.md").is_file() or (cur / ".anchor" / "ANCHOR.md").is_file():
            return cur
        if (cur / "scripts" / "anchor_client.py").is_file() and (cur / "mcp").is_dir():
            return cur  # Anchor source tree
    return p


REPO_ROOT = project_root_from()
DEFAULT_REGISTRY = Path(__file__).resolve().parent / "endpoints.yaml"
THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)
# Fleet Authorization: first present wins. NVIDIA_API_KEY is the Build inference
# key; NGC_API_KEY is a NIM-pull fallback (may lack inference scope).
API_KEY_ENV = ("ANCHOR_API_KEY", "NVIDIA_API_KEY", "NGC_API_KEY")


def load_dotenv(path: Path | None = None) -> Path | None:
    """Load ``KEY=VALUE`` from a gitignored ``.env`` into ``os.environ``.

    Already-exported variables win (setdefault). Returns the first path that
    existed, or None. Never prints values.
    """
    candidates: list[Path] = []
    if path is not None:
        candidates.append(Path(path))
    else:
        candidates.extend((Path.cwd() / ".env", REPO_ROOT / ".env"))
    loaded: Path | None = None
    seen: set[Path] = set()
    for raw_path in candidates:
        p = raw_path.resolve()
        if p in seen or not p.is_file():
            continue
        seen.add(p)
        if loaded is None:
            loaded = p
        for line in p.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            if s.startswith("export "):
                s = s[7:].strip()
            key, _, val = s.partition("=")
            key = key.strip()
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            if key and key not in os.environ:
                os.environ[key] = val
    return loaded


def request_api_key(env: dict[str, str] | None = None) -> tuple[str | None, str | None]:
    """``(key, env_var_name)`` for the Authorization header; never logs the key."""
    source = env if env is not None else os.environ
    for name in API_KEY_ENV:
        value = source.get(name)
        if value:
            return value, name
    return None, None

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


class RegistryConflict(ValueError):
    """Duplicate endpoint ``name:`` or alias across the merged registry."""


def overlay_paths(project_root: Path | None = None) -> list[Path]:
    """Machine-local overlay files (home config, then project ``var/``)."""
    found: list[Path] = []
    cfg = Path(os.environ.get("ANCHOR_CONFIG_DIR") or (Path.home() / ".config/anchor"))
    home = cfg / "endpoints.local.yaml"
    if home.is_file():
        found.append(home)
    root = Path(project_root) if project_root is not None else Path.cwd()
    var = root / "var" / "endpoints.local.yaml"
    if var.is_file() and var.resolve() not in {p.resolve() for p in found}:
        found.append(var)
    return found


def endpoint_from_mapping(row: dict) -> Endpoint:
    """Build an ``Endpoint`` from a registry YAML mapping (unknown keys dropped)."""
    aliases = row.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [aliases]
    return Endpoint(
        name=str(row["name"]),
        tier=str(row.get("tier") or "executor"),
        base_url=str(row.get("base_url") or ""),
        model=str(row.get("model") or row["name"]),
        quirks=dict(row.get("quirks") or {}),
        local=row.get("local"),
        aliases=[str(a) for a in aliases if str(a).strip()],
        machine=(str(row["machine"]) if row.get("machine") not in (None, "") else None),
        effort=(str(row["effort"]).strip().lower() if row.get("effort") not in (None, "") else None),
    )


def _merge_endpoint_rows(base: list[dict], overlay: list[dict]) -> list[dict]:
    by_name: dict[str, dict] = {}
    order: list[str] = []
    for row in base:
        name = row.get("name")
        if not name:
            continue
        by_name[str(name)] = dict(row)
        order.append(str(name))
    for row in overlay:
        name = row.get("name")
        if not name:
            continue
        name = str(name)
        if name in by_name:
            cur = by_name[name]
            extra = row.get("aliases") or []
            if isinstance(extra, str):
                extra = [extra]
            aliases = list(cur.get("aliases") or [])
            if isinstance(aliases, str):
                aliases = [aliases]
            for a in extra:
                if a not in aliases:
                    aliases.append(a)
            cur["aliases"] = aliases
            if row.get("machine") not in (None, ""):
                cur["machine"] = row["machine"]
            if row.get("effort") not in (None, ""):
                cur["effort"] = row["effort"]
            for key, val in row.items():
                if key in {"name", "aliases", "machine", "effort"} or val is None:
                    continue
                cur[key] = val
        else:
            by_name[name] = dict(row)
            order.append(name)
    return [by_name[n] for n in order]


def load_endpoint_rows(
    registry_path: str | Path,
    overlays: list[Path] | tuple[Path, ...] = (),
) -> list[dict]:
    data = yaml.safe_load(Path(registry_path).read_text(encoding="utf-8")) or {}
    rows = list(data.get("endpoints") or [])
    for ov in overlays:
        path = Path(ov)
        if not path.is_file():
            continue
        extra = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        rows = _merge_endpoint_rows(rows, list(extra.get("endpoints") or []))
    return rows


def build_alias_index(endpoints: list[Endpoint]) -> dict[str, Endpoint]:
    idx: dict[str, Endpoint] = {}
    for ep in endpoints:
        keys = [ep.name, *ep.aliases]
        for key in keys:
            if not key:
                continue
            prev = idx.get(key)
            if prev is not None and prev.name != ep.name:
                raise RegistryConflict(
                    f"alias {key!r} maps to both {prev.name!r} and {ep.name!r}"
                )
            idx[key] = ep
    return idx


def write_endpoint_nick(
    overlay: Path,
    *,
    alias: str,
    endpoint: str,
    machine: str | None = None,
    effort: str | None = None,
    registry_path: str | Path | None = None,
    overlays: list[Path] | None = None,
) -> Endpoint:
    """Record *alias* on *endpoint* in *overlay* only (never the shared registry)."""
    alias = str(alias).strip()
    if not alias:
        raise RegistryConflict("nickname is empty")
    fleet = Fleet(
        registry_path or DEFAULT_REGISTRY,
        overlays=overlays if overlays is not None else [],
        probe_health=False,
    )
    try:
        canon = fleet.lookup(endpoint)
    except LookupError as exc:
        raise RegistryConflict(str(exc)) from exc
    if alias != canon.name:
        hit = fleet._by_key.get(alias)
        if hit is not None and hit.name != canon.name:
            raise RegistryConflict(
                f"alias {alias!r} already maps to {hit.name!r}"
            )
    overlay = Path(overlay)
    overlay.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if overlay.is_file():
        data = yaml.safe_load(overlay.read_text(encoding="utf-8")) or {}
    rows = list(data.get("endpoints") or [])
    found = False
    for row in rows:
        if row.get("name") == canon.name:
            aliases = list(row.get("aliases") or [])
            if isinstance(aliases, str):
                aliases = [aliases]
            if alias not in aliases and alias != canon.name:
                aliases.append(alias)
            row["aliases"] = aliases
            if machine is not None:
                row["machine"] = machine
            if effort is not None:
                row["effort"] = str(effort).strip().lower()
            found = True
            break
    if not found:
        row = {"name": canon.name, "aliases": []}
        if alias != canon.name:
            row["aliases"] = [alias]
        if machine is not None:
            row["machine"] = machine
        if effort is not None:
            row["effort"] = str(effort).strip().lower()
        rows.append(row)
    data["endpoints"] = rows
    overlay.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    merged = Fleet(
        registry_path or DEFAULT_REGISTRY,
        overlays=[*(overlays or []), overlay],
        probe_health=False,
    )
    return merged.lookup(canon.name)


@dataclass
class Endpoint:
    name: str
    tier: str
    base_url: str
    model: str
    quirks: dict = field(default_factory=dict)
    # Set after a 400 on body `think` so later calls (and budget retries) skip it.
    _think_unsupported: bool = field(default=False, init=False, repr=False)
    local: bool | None = None
    aliases: list[str] = field(default_factory=list)
    machine: str | None = None
    effort: str | None = None

    @property
    def is_local(self) -> bool:
        """Does this endpoint run on hardware the operator powers?

        Explicit ``local:`` in the registry wins; otherwise the base URL decides
        (loopback / private ranges / ``.local``-style hostnames). Only local
        endpoints are subject to the site inference-load cap.
        """
        if endpoint_is_local is None:  # standalone copy without the governor
            return bool(self.local) if self.local is not None else False
        # One implementation of "is this local", so a value like `local: "false"`
        # cannot mean different things to work_once and to the MCP.
        return endpoint_is_local({"local": self.local, "base_url": self.base_url})

    def chat(self, messages: list[dict], *, thinking: bool = False,
             temperature: float | None = None, max_tokens: int = 4096,
             timeout: int = 600, _budget_retry: bool = False) -> str:
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

        # Thinking locals often burn a small max_tokens on reasoning and leave
        # content empty — floor before the context ceiling clamp.
        floor = self.quirks.get("min_completion_tokens")
        if floor:
            max_tokens = max(max_tokens, int(floor))

        # An endpoint's max_context is a hard serving ceiling; never request a
        # completion larger than the context that has to hold it.
        ceiling = self.quirks.get("max_context")
        if ceiling:
            max_tokens = min(max_tokens, int(ceiling))

        headers = {}
        api_key, _src = request_api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {"model": self.model, "messages": msgs,
                   "temperature": temperature, "max_tokens": max_tokens}
        # Extra per-endpoint sampling params (top_p, top_k, ...), e.g. Qwen3 thinking
        # wants top_p 0.95 / top_k 20. The resolved temperature above always wins.
        extra = self.quirks.get("sampling_thinking" if thinking else "sampling")
        if extra:
            payload = {**extra, **payload}
        # Grok-family reasoning dial (4.5/4.6). xhigh is 4.6-only at the API.
        reff = self.quirks.get("reasoning_effort") or self.effort
        if reff:
            payload["reasoning_effort"] = str(reff).strip().lower()
        # Ollama OpenAI extension: body `think` mirrors the call flag when the
        # quirk key is present (Ollama opt-in). Skip once a prior 400 cached
        # that this endpoint rejects the field.
        send_think = "openai_think" in self.quirks and not self._think_unsupported
        if send_think:
            payload["think"] = bool(thinking)

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        resp = _post_with_retry(url, json=payload, headers=headers, timeout=timeout)
        # Feature-detect: non-Ollama servers may 400 on unknown `think`.
        if send_think and resp.status_code == 400 and "think" in payload:
            self._think_unsupported = True
            payload = {k: v for k, v in payload.items() if k != "think"}
            resp = _post_with_retry(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
        choice = body["choices"][0]
        message = choice.get("message") or {}
        text = message.get("content") or ""
        if self.quirks.get("strip_think") or toggle:
            text = THINK_RE.sub("", text)
        text = text.strip()
        if text:
            return text

        # Empty content after a 200 is never silent success. Prefer one recovery
        # attempt (think-off + higher budget) over returning chain-of-thought.
        reasoning = (message.get("reasoning") or message.get("thinking") or "")
        finish = choice.get("finish_reason")
        if not _budget_retry:
            bump = max(max_tokens * 2, int(floor or 0), 256)
            if ceiling:
                bump = min(bump, int(ceiling))
            if bump > max_tokens or thinking:
                return self.chat(
                    messages,
                    thinking=False,
                    temperature=temperature,
                    max_tokens=bump,
                    timeout=timeout,
                    _budget_retry=True,
                )
        detail = f"finish_reason={finish!r}"
        if reasoning:
            detail += f", reasoning_chars={len(str(reasoning))}"
        raise EmptyAssistantText(
            f"{self.name}: empty assistant content after HTTP 200 ({detail}); "
            "refusing silent empty string (raise max_tokens / check think-off)"
        )


HEALTH_TIMEOUT_S = 3.0
NVIDIA_BUILD_ENDPOINT_NAME = "nvidia-build"


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def endpoint_reachable(ep: Endpoint, *, timeout: float = HEALTH_TIMEOUT_S) -> bool:
    """Cheap GET ``{base_url}/models``. Unreachable or non-2xx is False."""
    url = ep.base_url.rstrip("/") + "/models"
    try:
        resp = requests.get(url, timeout=timeout)
    except requests.RequestException:
        return False
    return resp.status_code == 200


class Fleet:
    def __init__(
        self,
        registry_path: str | Path = DEFAULT_REGISTRY,
        *,
        prefer_local: bool | None = None,
        probe_health: bool = True,
        overlays: list[Path] | None = None,
        overlay_root: Path | None = None,
    ):
        path = Path(registry_path)
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        ovs = overlays if overlays is not None else overlay_paths(overlay_root) if overlay_root is not None else []
        rows = load_endpoint_rows(path, ovs)
        self.endpoints = [endpoint_from_mapping(e) for e in rows]
        self._by_key = build_alias_index(self.endpoints)
        self.roles: dict[str, list[str]] = data.get("roles", {})
        self._rr: dict[str, int] = {}
        self._health: dict[str, bool] = {}
        if prefer_local is None:
            prefer_local = _truthy_env("ANCHOR_PREFER_LOCAL")
        self.prefer_local = bool(prefer_local)
        self.probe_health = probe_health

    def lookup(self, name: str) -> Endpoint:
        """Resolve a canonical ``name:`` or an overlay alias."""
        ep = self._by_key.get(name)
        if ep is None:
            raise LookupError(f"endpoint {name!r} not found in the registry")
        return ep

    def by_tier(self, tier: str) -> list[Endpoint]:
        return [e for e in self.endpoints if e.tier == tier]

    def _is_healthy(self, ep: Endpoint) -> bool:
        if not self.probe_health:
            return True
        cached = self._health.get(ep.name)
        if cached is not None:
            return cached
        ok = endpoint_reachable(ep)
        self._health[ep.name] = ok
        return ok

    def pick(self, role: str) -> Endpoint:
        """First *reachable* endpoint for a role, round-robin within the tier.

        Unreachable LAN rows are skipped (connect timeout ~``HEALTH_TIMEOUT_S``).
        When none remain and NVIDIA Build is configured+reachable, return a
        hosted Build endpoint — unless ``prefer_local`` / ``ANCHOR_PREFER_LOCAL``.
        """
        skipped: list[str] = []
        for tier in self.roles.get(role, []):
            candidates = self.by_tier(tier)
            healthy = []
            for ep in candidates:
                if self._is_healthy(ep):
                    healthy.append(ep)
                else:
                    skipped.append(ep.name)
            if not healthy:
                continue
            i = self._rr.get(tier, 0)
            self._rr[tier] = (i + 1) % len(healthy)
            return healthy[i % len(healthy)]
        build_note = "not tried (prefer_local)"
        if not self.prefer_local:
            fb, build_note = self._nvidia_build_fallback()
            if fb is not None:
                skipped_s = ", ".join(skipped) if skipped else "none"
                print(
                    f"[fleet] using NVIDIA Build ({fb.base_url}) — {build_note}; "
                    f"LAN skipped: {skipped_s}",
                    file=sys.stderr,
                )
                return fb
        raise LookupError(
            f"No healthy endpoint for role '{role}' "
            f"(tiers tried: {self.roles.get(role)}; "
            f"skipped unreachable: {skipped or 'none'}; "
            f"NVIDIA Build: {build_note})"
        )

    def _nvidia_build_fallback(self) -> tuple[Endpoint | None, str]:
        try:
            import nvidia_build_probe as nbp
        except ImportError:
            return None, "nvidia_build_probe missing"
        probe = nbp.probe_build()
        backend = nbp.preferred_backend(probe, prefer_local=self.prefer_local)
        if backend != "build":
            return None, nbp.explain(probe, backend, prefer_local=self.prefer_local)
        model = nbp.choose_build_model(nbp.list_build_model_ids(probe))
        if model in nbp.RETIRED_BUILD_MODELS or model.endswith(
            "llama-3.3-nemotron-super-49b-v1"
        ):
            model = nbp.DEFAULT_BUILD_MODEL
        ep = Endpoint(
            name=NVIDIA_BUILD_ENDPOINT_NAME,
            tier="reasoner",
            base_url=nbp.BUILD_BASE_URL,
            model=model,
            quirks={"think_toggle": "nemotron", "temperature": 0},
            local=False,
        )
        note = (
            f"key from {probe.key_source}, reachable, model={model}"
        )
        return ep, note


def resolve_doctrine_path(rel: str, root: Path | None = None) -> Path:
    """Resolve a doctrine/template path under *root* (default: REPO_ROOT).

    Accepts ``anchor/...`` or ``.anchor/...``. Tries the given form first, then
    the alternate prefix so both the Anchor source tree (``anchor/``) and
    scaffolded projects (``.anchor/``) work.
    """
    base = root if root is not None else REPO_ROOT
    rel_n = rel.replace("\\", "/")
    if rel_n.startswith("./"):
        rel_n = rel_n[2:]
    candidates = [base / rel_n]
    if rel_n.startswith("anchor/"):
        candidates.append(base / (".anchor/" + rel_n[len("anchor/") :]))
    elif rel_n.startswith(".anchor/"):
        candidates.append(base / ("anchor/" + rel_n[len(".anchor/") :]))
    for path in candidates:
        if path.is_file():
            return path
    tried = ", ".join(str(c) for c in candidates)
    raise FileNotFoundError(f"Doctrine file not found (tried: {tried})")


def load_prompt(rel: str) -> str:
    """Load a prompt/template, e.g. 'anchor/system-prompts/mythos-core.md'."""
    return resolve_doctrine_path(rel).read_text(encoding="utf-8")


REQUIRED_FOOTER = ("## Result", "## How to verify")


def has_required_footer(text: str) -> bool:
    return all(h in text for h in REQUIRED_FOOTER)

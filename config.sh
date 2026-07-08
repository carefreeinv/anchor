#!/usr/bin/env bash
# config.sh — Anchor initial-config helper.
#
# Asks which platform(s), fleet tooling, default language/framework, and preferred
# model priority you want, saves the answer under ~/.config/anchor/defaults, and
# prints the exact `anchor <project-dir>` command to scaffold a project with those
# defaults. Safe to re-run any time to change your mind. The language default is
# proposed (not forced) by anchor.py's framework survey when a project's framework
# can't be detected — e.g. propose node if the project is blank and you've said so.
# The model priority is your personal order for reaching for / escalating between
# models (cheapest-first is the usual convention), highest priority first.
#
# Usage:
#   ./config.sh                                             interactive prompts
#   ./config.sh --platform claude,grok --fleet --language node \
#     --model-priority nim,grok,claude:sonnet,claude:opus,claude:fable   non-interactive
#   ./config.sh --show                                      print saved defaults and exit
#
# Backs the /config command in Claude Code and Grok Build — see
# .claude/commands/config.md and platforms/grok-build/commands/config.md.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_DIR="${ANCHOR_CONFIG_DIR:-$HOME/.config/anchor}"
CONFIG_FILE="$CONFIG_DIR/defaults"
HELP_URL="https://carefreeinv.com/anchor"

VALID_PLATFORMS=(claude grok nemotron local chat)
VALID_LOCAL_MODELS=(qwen3 gemma3 mistral-small deepseek-r1-distill llama33)
# Model-priority tokens: a known provider, optionally with a free-form ":<model/tier>"
# (e.g. claude:sonnet, openai:gpt-5, gemini:2.5-pro). Provider is validated; the model
# after ":" is free-form so specific versions never go stale in a hardcoded list.
VALID_PRIORITY_PROVIDERS=(claude openai chatgpt gemini grok nim local chat)

usage() {
  cat <<'EOF'
Usage:
  ./config.sh                                             interactive prompts
  ./config.sh --platform claude,grok --fleet --language node \
    --model-priority nim,grok,claude:sonnet,claude:opus,claude:fable   non-interactive
  ./config.sh --show                                      print saved defaults and exit

Platforms: claude, grok, nemotron, local:<model>, chat
Local models: qwen3, gemma3, mistral-small, deepseek-r1-distill, llama33
Language: free-form (e.g. node, python, rust, go, java, ruby, dotnet, php) — proposed
          as the default answer in anchor.py's framework survey, never enforced.
Model priority: ordered, comma-separated, highest priority first. Providers:
          claude, openai (ChatGPT), gemini, grok, nim, local, chat — optionally with a
          specific model after a colon (claude:sonnet, openai:gpt-5, gemini:2.5-pro).
EOF
}

platform_arg=""
fleet_flag="0"
language_arg=""
priority_arg=""
show_only="0"

while [ $# -gt 0 ]; do
  case "$1" in
    --platform) platform_arg="$2"; shift 2 ;;
    --platform=*) platform_arg="${1#--platform=}"; shift ;;
    --fleet) fleet_flag="1"; shift ;;
    --language) language_arg="$2"; shift 2 ;;
    --language=*) language_arg="${1#--language=}"; shift ;;
    --model-priority) priority_arg="$2"; shift 2 ;;
    --model-priority=*) priority_arg="${1#--model-priority=}"; shift ;;
    --show) show_only="1"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 1 ;;
  esac
done

if [ "$show_only" = "1" ]; then
  if [ -f "$CONFIG_FILE" ]; then
    echo "Saved defaults ($CONFIG_FILE):"
    cat "$CONFIG_FILE"
  else
    echo "No saved defaults yet. Run ./config.sh to set them."
  fi
  exit 0
fi

validate_platform_key() {
  local key="$1" base sub ok m
  base="${key%%:*}"
  sub="${key#*:}"
  ok="0"
  for p in "${VALID_PLATFORMS[@]}"; do
    if [ "$p" = "$base" ]; then
      ok="1"
    fi
  done
  if [ "$ok" != "1" ]; then
    echo "Unknown platform '$key'. Valid: ${VALID_PLATFORMS[*]} (local also takes local:<model>)." >&2
    exit 1
  fi
  if [ "$base" = "local" ]; then
    if [ "$sub" = "local" ] || [ -z "$sub" ]; then
      echo "local requires a model, e.g. local:qwen3. Valid: ${VALID_LOCAL_MODELS[*]}" >&2
      exit 1
    fi
    ok="0"
    for m in "${VALID_LOCAL_MODELS[@]}"; do
      if [ "$m" = "$sub" ]; then
        ok="1"
      fi
    done
    if [ "$ok" != "1" ]; then
      echo "Unknown local model '$sub'. Valid: ${VALID_LOCAL_MODELS[*]}" >&2
      exit 1
    fi
  fi
}

validate_priority_key() {
  local key="$1" base ok p
  base="${key%%:*}"   # provider before an optional ":<model/tier>"
  ok="0"
  for p in "${VALID_PRIORITY_PROVIDERS[@]}"; do
    if [ "$p" = "$base" ]; then
      ok="1"
    fi
  done
  if [ "$ok" != "1" ]; then
    echo "Unknown model provider '$base' in '$key'. Valid providers: ${VALID_PRIORITY_PROVIDERS[*]}." >&2
    echo "Add a specific model after a colon, e.g. claude:sonnet, openai:gpt-5, gemini:2.5-pro." >&2
    exit 1
  fi
}

echo "Anchor setup — $HELP_URL"
echo

platform_keys=()
language="$(echo "$language_arg" | xargs | tr '[:upper:]' '[:lower:]')"
priority_raw="$priority_arg"

if [ -n "$platform_arg" ]; then
  IFS=',' read -ra platform_keys <<< "$platform_arg"
elif [ -t 0 ]; then
  echo "Which platform(s) do you want as your default?"
  echo "  1. claude     Claude Code"
  echo "  2. grok       Grok Build"
  echo "  3. nemotron   NVIDIA NIM / Nemotron"
  echo "  4. local      Local models (Qwen3, Gemma 3, Mistral Small, DeepSeek-R1 distill, Llama 3.3)"
  echo "  5. chat       Generic chat UI (ChatGPT-style, no tool execution)"
  echo
  read -rp "Enter numbers, comma-separated (e.g. 1,2): " raw_choice
  if [ -z "$raw_choice" ]; then
    echo "No selection made. Aborting." >&2
    exit 1
  fi
  nums=()
  IFS=',' read -ra nums <<< "$raw_choice"
  for n in "${nums[@]}"; do
    n="$(echo "$n" | xargs)"
    case "$n" in
      1) platform_keys+=("claude") ;;
      2) platform_keys+=("grok") ;;
      3) platform_keys+=("nemotron") ;;
      4)
        read -rp "Which local model(s)? (${VALID_LOCAL_MODELS[*]}): " local_raw
        local_names=()
        IFS=',' read -ra local_names <<< "$local_raw"
        for lm in "${local_names[@]}"; do
          lm="$(echo "$lm" | xargs)"
          if [ -n "$lm" ]; then
            platform_keys+=("local:$lm")
          fi
        done
        ;;
      5) platform_keys+=("chat") ;;
      *) echo "Invalid selection '$n'." >&2; exit 1 ;;
    esac
  done
  echo
  read -rp "Include fleet/orchestration tooling (scripts/, mcp/) by default? [y/N]: " fleet_raw
  case "$fleet_raw" in
    y|Y|yes|Yes) fleet_flag="1" ;;
  esac
  if [ -z "$language" ]; then
    echo
    read -rp "Default language/framework for blank/undetectable projects (e.g. node, python, rust, go, java, ruby, dotnet, php; blank for none): " language_raw
    language="$(echo "$language_raw" | xargs | tr '[:upper:]' '[:lower:]')"
  fi
  if [ -z "$priority_raw" ]; then
    echo
    echo "Rank the models you reach for, highest priority first (comma-separated)."
    echo "The usual convention is cheapest-first, escalating to frontier last."
    echo "Providers: claude, openai (ChatGPT), gemini, grok, nim, local, chat —"
    echo "add a specific model after a colon, e.g. claude:sonnet, openai:gpt-5, gemini:2.5-pro."
    read -rp "e.g. nim,grok,openai:gpt-5,claude:sonnet,claude:opus,claude:fable (blank to skip): " priority_input
    priority_raw="$priority_input"
  fi
else
  echo "No --platform given and no interactive terminal available." >&2
  usage >&2
  exit 1
fi

if [ "${#platform_keys[@]}" -eq 0 ]; then
  echo "No platform selected. Aborting." >&2
  exit 1
fi

for key in "${platform_keys[@]}"; do
  validate_platform_key "$key"
done

platforms_csv="$(IFS=,; echo "${platform_keys[*]}")"

# Model priority: split the raw csv, trim/lowercase each token, validate the provider.
priority_keys=()
if [ -n "$priority_raw" ]; then
  raw_parts=()
  IFS=',' read -ra raw_parts <<< "$priority_raw"
  for p in "${raw_parts[@]}"; do
    p="$(echo "$p" | xargs | tr '[:upper:]' '[:lower:]')"
    if [ -n "$p" ]; then
      priority_keys+=("$p")
    fi
  done
  for key in "${priority_keys[@]}"; do
    validate_priority_key "$key"
  done
fi
priority_csv="$(IFS=,; echo "${priority_keys[*]:-}")"

mkdir -p "$CONFIG_DIR"
{
  echo "# Written by config.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "PLATFORMS=$platforms_csv"
  echo "FLEET=$fleet_flag"
  if [ -n "$language" ]; then
    echo "LANGUAGE=$language"
  fi
  if [ -n "$priority_csv" ]; then
    echo "MODEL_PRIORITY=$priority_csv"
  fi
} > "$CONFIG_FILE"

echo
echo "Saved defaults to $CONFIG_FILE"
if [ -n "$language" ]; then
  echo "Default language/framework: $language (proposed, not forced, when anchor.py can't detect one)"
fi
if [ -n "$priority_csv" ]; then
  echo "Model priority (highest first): $priority_csv"
fi
echo
echo "From now on, this scaffolds a project using those defaults automatically:"
echo "  $REPO_ROOT/bin/anchor <project-dir>"
echo

fleet_suffix=""
if [ "$fleet_flag" = "1" ]; then
  fleet_suffix=" --fleet"
fi

echo "Equivalent explicit command:"
echo "  $REPO_ROOT/bin/anchor <project-dir> --platform $platforms_csv$fleet_suffix"
if [ -n "$language" ]; then
  echo "(anchor.py will still detect a project's real framework first and only fall back to"
  echo " '$language' when it can't — pass --framework $language yourself to force it instead.)"
fi
echo
echo "Tip: symlink bin/anchor onto your PATH (see README) so you can just run 'anchor <project-dir>' from anywhere."
echo
echo "Need help? $HELP_URL"

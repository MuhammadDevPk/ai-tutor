#!/usr/bin/env bash
set -euo pipefail

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

ROOT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT_DIR"

MODE="${1:---fast}"
TMP_LOG=$(mktemp)
trap 'rm -f "$TMP_LOG"' EXIT

run_step() {
  local label="$1"
  shift
  if "$@" >"$TMP_LOG" 2>&1; then
    echo "PASS: $label"
  else
    echo "FAIL: $label" >&2
    tail -n 60 "$TMP_LOG" >&2
    exit 1
  fi
}

# 1. Architectural Guardrails (Manifest + Import Scoped — No Comment False Positives)
check_banned_patterns() {
  local failed=0

  # A1. Frontend manifest (includes katex, tldraw, RPM, HeadTTS, Redis, and DB drivers)
  if [ -f "apps/web/package.json" ]; then
    if grep -rnE \
      '"(readyplayerme|@readyplayerme/[^"]+|headtts|tldraw|@tldraw/[^"]+|langgraph|drizzle-orm|@prisma/client|prisma|redis|ioredis|pg|postgres|katex)"' \
      apps/web/package.json; then
      echo "Forbidden frontend dependency found in apps/web/package.json (see .agents/PATTERNS.md)."
      failed=1
    fi
  fi

  # A2. Backend manifest (catches hyphenated packages like langgraph-checkpoint-postgres)
  if [ -f "apps/api/pyproject.toml" ]; then
    if grep -rnE \
      '^[[:space:]]*"?(langgraph|redis)([-<>=!~[:space:]"]|$)' \
      apps/api/pyproject.toml; then
      echo "Forbidden backend dependency found in apps/api/pyproject.toml (see .agents/PATTERNS.md)."
      failed=1
    fi
  fi

  # B. Actual Python import lines in apps/api
  if [ -d "apps/api" ]; then
    if grep -rnE \
      '^[[:space:]]*(from|import)[[:space:]]+(langgraph|redis)([[:space:].]|$)' \
      apps/api --include='*.py' --exclude-dir=.venv --exclude-dir=__pycache__; then
      echo "Forbidden Python import detected in apps/api."
      failed=1
    fi
  fi

  # C. Actual JS/TS import/require lines in apps/web/src
  if [ -d "apps/web/src" ]; then
    if grep -rnE \
      '(^[[:space:]]*(import|export)[[:space:]].*from[[:space:]]+|require\()[[:space:]]*["'\''](@readyplayerme|readyplayerme|headtts|tldraw|@tldraw|drizzle-orm|@prisma/client|redis|ioredis|pg|postgres|katex)([/"'\'']|$)' \
      apps/web/src --include='*.ts' --include='*.tsx' --include='*.js' --include='*.jsx'; then
      echo "Forbidden frontend import detected in apps/web/src (use MathJax 3 tex2svg, Excalidraw, and FastAPI client)."
      failed=1
    fi
  fi

  # D. Exact retired Groq model IDs and defunct Ready Player Me endpoints anywhere in source
  local code_dirs=()
  [ -d "apps/api" ] && code_dirs+=("apps/api")
  [ -d "apps/web/src" ] && code_dirs+=("apps/web/src")
  if [ ${#code_dirs[@]} -gt 0 ]; then
    if grep -rnE \
      '(llama-3\.1-8b-instant|llama-3\.3-70b-versatile|models\.readyplayer\.me|api\.readyplayer\.me)' \
      "${code_dirs[@]}" --exclude-dir=.venv --exclude-dir=node_modules --exclude-dir=.next; then
      echo "Retired Groq model ID or defunct Ready Player Me URL detected."
      failed=1
    fi
  fi

  return "$failed"
}
run_step "Architectural guardrails (Do-Not-Build)" check_banned_patterns

# 2. Backend Checks (apps/api)
if [ -f "apps/api/pyproject.toml" ]; then
  run_step "Python lint (ruff)" bash -c "cd apps/api && uv run ruff check ."
  run_step "Python types (mypy)" bash -c "cd apps/api && uv run mypy ."
  if [ "$MODE" = "--full" ]; then
    run_step "Python full test suite (pytest)" bash -c "cd apps/api && uv run pytest -q -m 'not slow' --tb=short"
  else
    run_pytest_fast() {
      local status=0
      (cd apps/api && uv run pytest -q -m 'not slow and not integration' --tb=short) || status=$?
      if [ "$status" -eq 5 ]; then
        echo "No fast unit tests collected yet (allowed in --fast; mandatory in --full)."
        return 0
      fi
      return "$status"
    }
    run_step "Python unit tests (pytest)" run_pytest_fast
  fi
fi

# 3. Frontend Checks (apps/web)
if [ -f "apps/web/package.json" ]; then
  run_step "Web typecheck (tsc)" bash -c "cd apps/web && pnpm exec tsc --noEmit"
  run_step "Web lint" bash -c "cd apps/web && pnpm run lint"
  if [ "$MODE" = "--full" ] && grep -q '"test"' apps/web/package.json; then
    run_step "Web tests" bash -c "cd apps/web && pnpm test -- --run"
  fi
  if [ "$MODE" = "--full" ]; then
    # Added by the operator after Phase 2: tsc + lint passed while
    # `next build` failed on a prerender error, so the full gate now builds.
    run_step "Web production build" bash -c "cd apps/web && pnpm build"
    run_step "Secrets-in-bundle check" bash -c "bash ./scripts/check-bundle-secrets.sh apps/web/.next"
  fi
fi

# 4. Full-Mode Phase Sign-Off Gates (Contract Drift + No Leftover Spikes)
if [ "$MODE" = "--full" ]; then
  check_no_spikes() {
    if [ -d "spikes" ]; then
      echo "Leftover spikes/ directory found. Log constants in .agents/DECISIONS.md and delete spikes/ before completing a phase."
      return 1
    fi
  }
  run_step "No leftover spikes/ directory" check_no_spikes

  if [ -f "package.json" ] && grep -q '"sync:contracts"' package.json; then
    check_contract_drift() {
      local target=""
      if [ -d "apps/web/src/lib/api-client" ] && find apps/web/src/lib/api-client -type f -print -quit | grep -q .; then
        target="apps/web/src/lib/api-client"
      elif [ -f "apps/web/src/lib/api-client.ts" ]; then
        target="apps/web/src/lib/api-client.ts"
      else
        echo "Expected generated OpenAPI client at apps/web/src/lib/api-client(.ts) was not found."
        return 1
      fi

      local before after
      before=$(find "$target" -type f | LC_ALL=C sort | xargs cksum)
      pnpm run sync:contracts
      after=$(find "$target" -type f | LC_ALL=C sort | xargs cksum)
      if [ "$before" != "$after" ]; then
        echo "OpenAPI client drifted at $target (pnpm run sync:contracts modified generated files)."
        return 1
      fi
    }
    run_step "OpenAPI contract drift check" check_contract_drift
  fi
fi

echo "ALL CHECKS PASSED ($MODE) @ $(git rev-parse --short HEAD 2>/dev/null || echo 'no-git')"

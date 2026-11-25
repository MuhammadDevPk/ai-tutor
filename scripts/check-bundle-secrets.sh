#!/usr/bin/env bash
# scripts/check-bundle-secrets.sh
# Scans apps/web/.next production build output for secret patterns and server-only env var names.
# Exits 0 if clean, exits 1 on any hit.

set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
TARGET_DIR="${1:-$ROOT_DIR/apps/web/.next}"

if [ ! -d "$TARGET_DIR" ]; then
  echo "ERROR: Target directory '$TARGET_DIR' does not exist." >&2
  echo "Run 'pnpm --filter web build' before running this check." >&2
  exit 2
fi

# Server-only environment variable names that must NEVER appear in the client bundle
SERVER_ENV_NAMES=(
  "GROQ_API_KEY"
  "GEMINI_API_KEY"
  "LIVEKIT_API_SECRET"
  "JWT_SECRET"
  "DATABASE_URL"
  "SUPABASE_DATABASE_URL"
  "DEV_USER_PASSWORD"
)

# Secret regex patterns
SECRET_PATTERNS=(
  'AIzaSy[0-9A-Za-z_-]{30,}'
  'gsk_[0-9A-Za-z_-]{20,}'
  'postgres(ql)?://[^:]+:[^@]+@'
  '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----'
)

FAILED=0
TMP_FOUND=$(mktemp)
trap 'rm -f "$TMP_FOUND"' EXIT

echo "Scanning '$TARGET_DIR' for leaked secrets and server-only env var names..."

# 1. Check for server-only env variable names in client static/chunks
for var_name in "${SERVER_ENV_NAMES[@]}"; do
  # Search .js, .html, .json files in target directory
  if grep -rnF "$var_name" "$TARGET_DIR" \
    --include="*.js" \
    --include="*.html" \
    --include="*.json" \
    --exclude="*.map" 2>/dev/null > "$TMP_FOUND"; then
    echo "LEAK DETECTED: Server-only env var name '$var_name' found in build output:" >&2
    cat "$TMP_FOUND" >&2
    FAILED=1
  fi
done

# 2. Check for secret regex patterns (filtering known public upstream vendor constants)
# Excalidraw's open-source bundle embeds its public demo Firebase API key:
# AIzaSyAd15pYlMci_xIp9ko6wkEsDzAAA0Dn0RU
EXCALIDRAW_PUBLIC_KEY="AIzaSyAd15pYlMci_xIp9ko6wkEsDzAAA0Dn0RU"

for pattern in "${SECRET_PATTERNS[@]}"; do
  matches=$(grep -rnE "$pattern" "$TARGET_DIR" \
    --include="*.js" \
    --include="*.html" \
    --include="*.json" \
    --exclude="*.map" 2>/dev/null | grep -v "$EXCALIDRAW_PUBLIC_KEY" || true)

  if [ -n "$matches" ]; then
    echo "LEAK DETECTED: Secret pattern '$pattern' matched in build output:" >&2
    echo "$matches" >&2
    FAILED=1
  fi
done

if [ "$FAILED" -ne 0 ]; then
  echo "FAIL: Secrets or server-only env var names detected in client bundle!" >&2
  exit 1
fi

echo "PASS: No secrets or server-only env var names found in '$TARGET_DIR'."
exit 0

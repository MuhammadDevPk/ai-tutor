# AGENTS.md — AI Video Tutor Engineering Contract

## Priority Order (Higher Priority Always Wins)
- **P0 (Safety & Boundaries):** Never push directly to `main`. Never read, print, or commit `.env*` files or secrets. Never bypass git hooks (`--no-verify` / `-n`). Require explicit human confirmation before running destructive DB migrations, resetting Supabase state, or changing deployment configs.
- **P1 (Pre-Phase Grill — Mandatory Before Coding):** Before editing any file for a new phase, read `.agents/PATTERNS.md`, `.agents/DECISIONS.md`, and the active phase in `.agents/ROADMAP.md`. Identify anything underspecified and ask **3–5 concrete decision questions** (each with a recommended default and trade-off). **Wait for human sign-off before writing code.**
- **P2 (Single Source of Truth):** `apps/api` (FastAPI + Alembic + `psycopg3`) is the sole database owner. `apps/web` never connects to Postgres or installs an ORM; it consumes only generated OpenAPI TypeScript/Zod clients.
- **P3 (Honest TDD Split — 5 Core Modules Only):** For these 5 pure-logic modules—**(1) line-stream parser, (2) `ltree` scoping repository, (3) Whisper backchannel/hallucination guard, (4) spatial whiteboard allocator, (5) playout clock scheduler**—write failing tests first, run them to prove they fail for the right reason, and **STOP for a 60-second human test review** before writing the implementation. For UI glue, CSS animations, and wiring, skip red-green-refactor theater.
- **P4 (Executed Verification Only):** Never claim checks pass from memory. Every implementation turn must end by running `./scripts/verify.sh` and reporting its exact command, exit code, and git HEAD.
- **P5 (Rule-Promotion Discipline):** Never add a new rule to `.agents/PATTERNS.md` or a check to `scripts/verify.sh` speculatively. Promote a lesson only after the same mistake occurs **twice**; record it in `.agents/DECISIONS.md` and retire rules that never fire.

## Exploratory Spikes (Allowed Escape Hatch)
Hardware and browser integration work (WebRTC AEC audio graph, Silero VAD room calibration, TalkingHead FLIP transforms) may use a timeboxed throwaway spike under `spikes/` to measure real behavior. Once measured, record calibrated constants in `.agents/DECISIONS.md`, delete `spikes/`, and implement cleanly. (`./scripts/verify.sh --full` blocks phase completion if `spikes/` still exists.)

## Context Hygiene
- Work on **one phase per session**. Do not start Phase N+1 until every Verification Gate in Phase N passes.
- If `./scripts/verify.sh` fails twice on the same root cause, stop patching blindly—state your hypothesis and ask the human before continuing.
- Keep diffs strictly scoped to the active phase; do not refactor unrelated files.

## Canonical Commands
- Fast checks (after edits): `./scripts/verify.sh --fast`
- Full checks (before phase sign-off): `./scripts/verify.sh --full`
- Sync OpenAPI contracts (`apps/api` -> `apps/web`): `pnpm run sync:contracts`

## Mandatory Final Report Format
1. **Changed files** (grouped by purpose: behavior, test, config)
2. **Executed verification** (exact command, exit code, and git HEAD)
3. **Unverified items** (live audio, browser DevTools, or manual checks still needed)

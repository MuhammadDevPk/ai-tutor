# DECISIONS.md — Calibrated Constants & Promoted Rules

## Pre-Phase Grill Decisions (Append per Phase)
- Phase 1 (approved by Malik, 2026-11-23):
  - **Database:** Local PostgreSQL for now (LOCAL-DEV OVERRIDE of the Supabase-first plan). Native local Postgres via `DATABASE_URL` in `.env`; commit `.env.example`; zero Docker/Redis. Migration 001 must enable and verify `vector` and `ltree` so moving to Supabase later is a one-line `DATABASE_URL` swap.
  - **Auth:** Lightweight FastAPI HS256 JWT with one seeded dev account. Abstracted behind a single `get_current_user()` dependency returning a valid **UUID** `user_id` (never a plain string), so `courses.user_id` (UUID) stays directly compatible with Supabase Auth later.
  - **Branch:** All Phase 1 work strictly on `phase-1-scaffold`.
  - **Merge policy (Malik, 2026-11-23):** Stacked branches — each phase branch builds on the previous phase branch; the agent never merges; Malik merges the stack in order himself.
  - **Tooling:** pnpm for `apps/web`, uv for `apps/api`. No substitutes.
  - **OpenAPI Contract Sync:** Kept in Phase 1. `pnpm run sync:contracts` exports FastAPI's OpenAPI JSON **offline via Python** (no running uvicorn server required) and generates the client under `apps/web/src/lib/api-client/`, so `./scripts/verify.sh --full` passes cleanly.

## Calibrated Runtime Constants (Measured Values Only)
- [ ] Silero VAD base threshold vs. elevated speaking-gate threshold
- [ ] Observed P50/P95 latencies per hop (VAD -> Whisper -> Groq -> Kokoro -> Client)
- [ ] Verified Groq model-bucket rotation threshold (default: rotate below 4,500 remaining TPM)
- [ ] Measured TalkingHead 30fps CPU % and FLIP duration on local laptop

## Promoted Harness Rules (Add Only After Same Mistake Repeats Twice)
- *(Empty — add only recurring defects; delete any rule that never triggers.)*

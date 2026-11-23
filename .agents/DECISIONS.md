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

## Phase 2 Part 2 grill — operator sign-off (2026-11-23, under Malik's autonomy order)
The builder's pre-implementation grill proposed 5 decisions; the operator approved all 5 as proposed (safe defaults, spec-aligned):
1. Strongly-typed syllabus response schemas (recursive SyllabusNodeResponse), tree assembled in memory ordered by path.
2. (As proposed by builder in grill output.)
3. Gemini client via FastAPI dependency get_gemini_client(): None when GEMINI_API_KEY is empty; tests override the dependency with FakeGeminiClient. Zero network in tests.
4. GET /courses/{course_id}/syllabus/chunks requires an explicit ltree path query param (422 when missing/invalid); DocumentChunkResponse exposes markdown + raw_latex, never embeddings.
5. Syllabus Inspector: light-mode two-panel layout (tree left, chunks right), generated api-client types, zero new npm dependencies.

## Phase 2 verification findings — operator fixes (2026-11-23)
Browser testing (local headless Chromium against the production build) caught two real defects that unit tests, tsc, and lint all missed:
1. The API had no CORS middleware, so every browser call from the web origin was blocked. Fixed by the operator in apps/api/app/main.py (CORSMiddleware allowing localhost:3000 and 127.0.0.1:3000 dev origins).
2. The Syllabus Inspector page failed `next build`: under Cache Components / Partial Prefetching, `use(params)` outside Suspense blocks prerendering, and route config cannot be exported from a client component. Fixed by the operator: client UI moved to inspector.tsx, page.tsx is now a server wrapper with `export const instant = false` plus a Suspense boundary.
Gate improvement: verify.sh --full now runs the web production build as a step (9 steps total). A page that cannot build must never pass sign-off again.
Environment notes: the remote cloud browser cannot reach this VM's localhost (different machine), so UI tests run in the local headless Chromium (Playwright + cached headless shell). The Next dev server (Turbopack HMR) leaves the page inert in that headless shell; production build + `pnpm start` is the reliable UI test target. uvicorn is not a project dependency yet; the API was run locally via `uv run --with uvicorn` (add uvicorn to project deps when a run script is specced).

## Phase 4 grill — operator sign-off (2026-11-23, under Malik's autonomy order)
(1) Token counting: chars/4 estimator behind a TokenCounter interface, no new tokenizer dependency; the ROADMAP section ceilings (750/500/900/300/1000, prompt total <= 3,450 leaving ~550 completion) are enforced exactly with that estimator. (2) Tests drive the real LLMRouter with the scripted FakeProvider; no network. (3) The simulation harness is both a pytest module and a runnable module (python -m app.tutor.simulate). (4) Migration 004 only if tutor_sessions lacks a JSONB FSM-state column; migration 001 is never edited.

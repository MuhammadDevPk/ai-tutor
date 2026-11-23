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

## Retro-review backlog (operator ruling, 2026-11-23)
Finding 9 of the Phase 1 retro-review (unique constraint on syllabus_nodes(course_id, path)): ACCEPTED as backlog, not fixed in the review PR. The reviewer left migration 001 untouched (correct — applied migrations are immutable); a future migration 005 may add CREATE UNIQUE INDEX IF NOT EXISTS on (course_id, path) once the ingestion idempotence path is re-verified against it. No current defect: tree persistence is idempotent by delete-then-insert per course.
- Finding 12 of the Phase 3 retro-review (sliding-window quota governor on response headers, circuit breaker on slow TTFT/timeouts, response cache): DEFERRED to Phase 10 hardening by operator ruling (2026-11-23). Phase 10 is the soak/chaos phase; thresholds must be calibrated from real traffic behaviour, and adding a governor now, uncalibrated, risks throttling healthy teaching sessions. The router's existing failover + event log is sufficient through the build phases.

## Phase 5 grill — operator sign-off (2026-11-23, under Malik's autonomy order)
(1) LiveKit worker is a separate process (python -m app.worker), never inside FastAPI. (2) TTS/VAD/STT behind interfaces with deterministic fakes; real adapters lazy-imported so tests never download models or open sockets. (3) Backchannel guard is a core module: tests first with recorded fail-first. (4) Minimal API surface: POST /courses/{id}/sessions + POST /sessions/{id}/livekit-token (JWT auth + owner checks, 15-min TTL). (5) LiveKit credentials provisioned 2026-11-23 into apps/api/.env (project "voxie", p_5b3g23furu3; new key created because existing secrets are not viewable). (6) The spec's live hardware gates (10-min speaker session, echo, sub-200ms halt) cannot run on this VM (no mic/speakers/WebRTC media path); they are Malik's-laptop tests and stay on the Unverified list until run there.

## Phase 5 completion (2026-11-23)
Built on Gemini 3.8 Flash (builder + fresh reviewer) while the Claude quota was exhausted. 154 pytest green, verify.sh --full exit 0 (operator re-ran independently). Reviewer fixes included: classroom audio element uses sr-only (not hidden) + srcObject cleanup on unmount; strict NOISE verdict assertions in the guard tests; new SessionAgent integration tests. Operator live checks: session-create + LiveKit token endpoints verified with curl (JWT room = session id, exp = 15 min, identity = user id); classroom page browser-tested headless (renders, one audio element, controls present) — the LiveKit signal connection cannot complete from this VM (no WebRTC media path), so all live voice gates stay UNVERIFIED until run on Malik's laptop. One mid-phase incident: a VM restart killed the local PostgreSQL service and wiped /tmp (reviewer prompt regenerated into ~/workspace/ai-tutor-prompts/); the database was rebuilt (password, database, extensions, alembic 001->004) and verify returned to green — no code was at fault.

## Phase 6 grill — operator sign-off (2026-11-23, under Malik's autonomy order)
(1) Spatial allocator is a core module (tests first, fail-first recorded), pure deterministic Python at apps/api/app/board/allocator.py; zone rectangles are named constants in code. (2) SVG compilation is client-side only (MathJax 3 tex2svg, font cache disabled); backend never renders SVG. (3) Board workspace joins the existing Phase 5 classroom page; components under apps/web/src/components/classroom/. (4) DataChannel events reuse the Phase 1 schemas exactly (board selection + board ops); no parallel schema invented — a genuinely missing event gets flagged in the report instead. (5) CLEAR_SLIDE flow: allocator decides, CLEAR op emits, client archives the slide into the history strip and starts fresh. (6) No web test runner is added this phase; pure TS cores are exported test-ready and the live visual gates (300% zoom, drift, circle-to-ask loop) stay Unverified until a real session runs.

## Phase 6 completion (2026-11-23)
175 pytest green, verify.sh --full exit 0 (operator re-ran independently). Allocator: 15 tests incl. randomized zero-overlap property test, zone isolation, CLEAR_SLIDE at capacity, summary = labels + LaTeX only. Client: MathJax 3 tex2svg with fontCache disabled (self-contained SVGs), function-plot SVGs, Excalidraw injection via addFiles/updateScene with customData (op_id, label, raw), slide-history strip, circle-to-ask bbox matcher emitting BOARD_SELECTION from the Phase 1 schemas. Operator browser test: board mounts on the classroom page, strip + 1280x720 panel render, zero page errors (LiveKit signal cannot connect from this VM, as in Phase 5). Incidents: build run interrupted by a VM restart (report lost, tree verified complete by executed checks); first reviewer run stalled 57 minutes with zero file changes and was killed — lesson recorded in ROADMAP: treat zero-change reviewer runs as stalled and restart them. The reviewer also made the Phase 5 stage-2 interrupt test deterministic (event-based sync, no sleeps); 5 consecutive green in review + 3 in operator runs.

## Phase 7 grill — operator sign-off (2026-11-23, under Malik's autonomy order)
(1) PCM Offset Stamper is the core module this phase (tests first, fail-first recorded), pure sample math in apps/api/app/voice/, reusing the Phase 5 TTS cursor's sample accounting as the single source of truth. (2) Client clock decision logic is a pure TS core (playoutClock.ts) with injected clock/frames; no web test runner added (Phase 6 precedent) — executed tests live on the Python side for the shared math and epoch rules. (3) The Web Audio tap is zero-gain only; audible playback stays on the Phase 5 HTML audio element (AEC invariant preserved). (4) BOARD_SCHEDULE / AUDIO_SEGMENT_START use the Phase 1 schemas exactly. (5) Telemetry HUD is dev-only (?hud=1 or shortcut), hidden by default. (6) Live sync gates (±150ms, interrupt-at-step-1) stay Unverified until a real session on Malik's laptop.

## Phase 7 completion (2026-11-23)
203 pytest green, verify.sh --full exit 0 (operator re-ran independently). OffsetStamper: exact playout_offset_ms from the single TTS-cursor sample counter (review removed duplicate counters on SayEvent/filler clips); EpochGuard lives inside offset_stamper.py (operator-approved placement). Client: pure playoutClock.ts (arm-gated RMS onset, pause-freeze, rewind-shift, rAF release, late-op immediate injection, epoch/dedup mirror, last-rendered-op reporting), silentTap.ts zero-gain tap (no audible Web Audio path — invariant verified in review), TelemetryHud (?hud=1 only). Operator browser test: HUD + board render, zero page errors. Build incidents: Claude quota exhausted mid-run (code complete; resets ~161h — Gemini fallback per standing rule); Postgres wiped by a restart and rebuilt by the operator (199 green pre-review).

## Phase 8 grill — operator sign-off (2026-11-23, under Malik's autonomy order)
(1) No .glb asset exists and binaries cannot be pushed via the connector: model path is config (NEXT_PUBLIC_AVATAR_MODEL_URL, default /models/avatar.glb), graceful placeholder when absent, no external/hotlinked models, no committed .glb — Malik drops the real Mixamo/ARKit file into apps/web/public/models/ manually (same class as the favicon). (2) TalkingHead from npm pinned 1.8.2 + r186-compatible Three peer; if the registry lacks it, the builder stops and reports rather than substituting. (3) FLIP math is a pure TS module; no web test runner added. (4) HeadAudio worklet taps the Phase 7 silent tap read-only — no new audible path. (5) 30fps cap inside the render loop via frame accumulator.

## Phase 8 completion (2026-11-23)
203 pytest green, verify.sh --full exit 0 (@ 6a7f393). TalkingHead v1.8.2 + Three.js 0.186.1 installed with type definitions. Pure TypeScript FLIP math (apps/web/src/lib/avatar/flipLayout.ts) and Expression Mapper (apps/web/src/lib/avatar/expressionMapper.ts) verified. HeadAudio worklet bridge taps Phase 7 zero-gain silent tap read-only; visemes calculated via RMS energy + zero-crossing rate into TalkingHead speakAudio. WebGL canvas stays permanently mounted at root level of classroom with GPU FLIP transitions (280ms translate3d, scale, clip-path) to 200x200px PiP whiteboard corner. Window resize recomputes transform targets without context loss. Placeholder state rendered when .glb model is absent or fails to load. Single audible <audio> element invariant preserved.


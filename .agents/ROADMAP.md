# ROADMAP.md — Active State & Phase Gates

## Current Session Handoff (Update at End of Every Session)
- **Active Phase:** Phase 8 — TalkingHead 3D avatar & GPU FLIP layout engine
- **Status:** Phase 7 PASSED (2026-11-23: verify.sh --full exit 0, 9 steps, 203 pytest green; PCM Offset Stamper core module (24 tests at build + 4 adversarial in review) computing exact playout_offset_ms from the single TTS-cursor sample counter; EpochGuard inside the stamper module (stale-turn rejection, op_id dedup, unrendered-op reconciliation for the resume_stack); client pure-TS playout clock with arm-gated RMS onset (filler never arms), pause-freeze and rewind-shift elapsed time, rAF release scheduling, late-op immediate injection; silent zero-gain Web Audio tap verified to carry no audible path; dev Telemetry HUD (?hud=1). Operator browser test: HUD renders with ?hud=1, board mounts, Circle-to-Ask Ready, one audio element, zero page errors. Incidents: the Claude builder hit its account quota near the end (code complete; operator rebuilt the wiped Postgres and re-ran the suite green at 199 before the Gemini review; Claude quota resets in ~161h, Gemini fallback per the standing rule).
- **Last Verified Commit:** phase-7-playout branch push (base: main after PR #9 merge)
- **Next Concrete Task:** Phase 8 TalkingHead avatar + FLIP layout (needs the avatar .glb asset decision — see blockers).
- **Open Blockers / Manual Checks Needed:** Phase 5/6/7 live gates (voice loop, zoom sharpness, +/-150ms sync, step-1 interrupt) remain UNVERIFIED — they need Malik's laptop. Phase 8 needs a self-hosted Mixamo/ARKit .glb avatar asset (no Ready Player Me per spec). Merge policy: autonomous open+merge for ai-tutor ONLY. Review flow: fresh Antigravity reviewer per phase; zero-change reviewer runs are stalled — restart them.
---
## Phase Index & Core TDD Checkpoints
- [x] **Phase 1:** Scaffold, Supabase `vector` + `ltree` migration, OpenAPI sync **[STOP-FOR-TEST-REVIEW: `ltree` scoping repository]** — PASSED 2026-11-23
- [x] **Phase 2:** Math-aware PDF ingestion, Gemini Vision fallback, Syllabus Inspector — PASSED 2026-11-23
- [x] **Phase 3:** Model-bucket LLM router & line-delimited stream parser **[STOP-FOR-TEST-REVIEW: line-stream parser]** — PASSED 2026-11-23
- [x] **Phase 4:** Explicit 5-state Pedagogical FSM & 4,000-token budget assembler — PASSED 2026-11-23
- [x] **Phase 5:** LiveKit voice transport, server Kokoro TTS & two-stage barge-in **[STOP-FOR-TEST-REVIEW: Whisper backchannel/hallucination guard]**
- [x] **Phase 6:** Excalidraw native-SVG whiteboard, spatial allocator & circle-to-ask **[STOP-FOR-TEST-REVIEW: spatial whiteboard allocator]**
- [x] **Phase 7:** Sample-accurate playout clock sync & barge-in rollback **[STOP-FOR-TEST-REVIEW: playout clock scheduler]**
- [ ] **Phase 8:** TalkingHead 3D avatar (30fps) & GPU FLIP Full-to-PiP transitions
- [ ] **Phase 9:** Reload persistence, interactive timeline replay & cheat-sheet exports
- [ ] **Phase 10:** 45-minute soak test, 429 chaos drill, Supabase keep-alive & $0 deploy

---
## Detailed Phase Specifications & Verification Gates (v2 plan, Section 4)

## 4. Complete 10-Phase AI-Agent Implementation Plan

Feed these phases to your coding agent sequentially. Each phase specifies what to build, the exact edge cases that must be handled, and the objective verification gates required before advancing.

### Phase 1: Repository Scaffold, .agents/ Harness & Single-Owner Schema

**Goal & Dependency:** Establish the monorepo, agent guardrails, Supabase PostgreSQL schema, and typed FastAPI-to-Next.js API contract pipeline with zero local database containers.

**Modules to Build:**

- Initialize the pnpm workspace (apps/web) with Next.js 16, React 19, strict TypeScript, and Light Mode Tailwind design tokens.
- Initialize the uv Python project (apps/api) with FastAPI, Pydantic v2, psycopg3, and Alembic.
- Populate .agents/ARCHITECTURE.md, .agents/PATTERNS.md, and .agents/ROADMAP.md with the locked topology, seven invariants, and Do-Not-Build list.
- Author Alembic migration 001 enabling vector and ltree extensions, creating all five tables (courses, syllabus_nodes, document_chunks, tutor_sessions, session_events), and attaching GiST indexes on ltree paths and an HNSW cosine index on 384d embeddings.
- Define Pydantic v2 schemas for course CRUD, syllabus inspection, session lifecycle, and all eight DataChannel event types; wire an automated openapi-typescript script generating typed clients and Zod validators into apps/web.
- Implement lightweight session/JWT authentication protecting all API routes and course CRUD endpoints.

**Required Behaviors & Edge Cases:**

- All database queries use parameterized async psycopg3 pools connected to Supabase; no ORM or Postgres driver exists in apps/web.
- Include a reusable repository helper that enforces the PostgreSQL ltree ancestor containment filter on every curriculum and chunk query so unscoped queries cannot be written accidentally.

**Verification Gates:**

- Both apps/web and apps/api start locally with zero Docker Postgres or Redis containers running.
- Integration test inserting mock Chapter 1 and Chapter 2 nodes verifies that querying with Chapter 1's path returns zero Chapter 2 rows in under 10ms.
- Adding a test field to a Pydantic schema and running the contract sync command updates apps/web TypeScript types cleanly with zero compiler errors.

### Phase 2: Math-Aware PDF Ingestion & Scoped RAG Pipeline

**Goal & Dependency:** Convert real university math, statistics, and physics handouts into formula-intact syllabus trees and strictly subtopic-bounded vector chunks. Depends on Phase 1.

**Modules to Build:**

- Async FastAPI background ingestion pipeline using PyMuPDF4LLM or Docling to parse PDFs into clean Markdown while preserving mathematical notation.
- Selective Vision fallback detector that flags pages with low extractable text density, broken symbol glyphs, or rasterized equation blocks and routes only those pages to gemini-3.8-flash Vision for clean LaTeX extraction.
- Curriculum Tree Extractor passing extracted headings and Table of Contents to gemini-3.8-flash (long-context free tier) to produce a validated syllabus_nodes hierarchy with canonical ltree paths (for example, sta301.ch01.t02_mean), learning objectives, key formulas, and summaries capped at 250 tokens.
- Formula-Preserving Chunker that splits text strictly within single subtopic boundaries, keeps display math blocks unbroken, stores raw LaTeX arrays alongside Markdown, embeds locally on CPU via fastembed (BAAI/bge-small-en-v1.5, 384d), and bulk-loads document_chunks.
- Light Mode Course & Syllabus Inspector UI in apps/web supporting PDF upload, live ingestion progress polling, navigable chapter/subtopic tree, math formula preview, manual heading correction, and a "Start Chapter" launcher.

**Required Behaviors & Edge Cases:**

- Never allow a single chunk to span two chapters or subtopics.
- Sanitize extracted headings into valid PostgreSQL ltree labels (alphanumeric and underscores only) so malformed PDF titles never fail database inserts.
- Make ingestion idempotent per uploaded document so retrying a failed PDF replaces partial nodes cleanly rather than duplicating chunks.

**Verification Gates:**

- Upload a multi-chapter university handout (such as a Statistics or Calculus PDF); all chapters and subtopics appear accurately in the Syllabus Inspector with intact LaTeX previews.
- Automated RAG test locked to Chapter 1 using strong Chapter 5 keywords returns zero chunks from Chapters 2 and beyond.

### Phase 3: Model-Bucket LLM Router & Line-Delimited Stream Parser

**Goal & Dependency:** Deliver rate-limit-proof, zero-cost streaming inference with byte-accurate LaTeX delivery and zero mid-lecture HTTP 429 outages. Depends on Phase 1.

**Modules to Build:**

- ModelBucketRouter in apps/api/llm implementing a single async streaming interface across three tiers:
  - Tier 1 (Groq single API key, three independent model buckets): openai/gpt-oss-20b, openai/gpt-oss-120b, and qwen/qwen3.8-27b.
  - Tier 2 (Google AI Studio free tier): gemini-3.8-flash and gemini-3.5-flash-lite.
  - Tier 3 (Offline emergency fallback): Local Ollama (invoked only if all cloud tiers fail or are unreachable).
- In-process sliding-window quota governor that inspects Groq response headers (x-ratelimit-remaining-tokens, x-ratelimit-remaining-requests, x-ratelimit-reset-tokens) after every turn and proactively rotates to the next healthy model bucket whenever remaining TPM falls below 4,500.
- Per-bucket circuit breaker (trips for 60 seconds after three consecutive timeouts or slow TTFT beyond 2.5 seconds) plus an in-process cachetools LRU cache keyed by normalized (syllabus_path, question_hash) for recurring foundational definitions.
- Incremental Line-Delimited Stream Parser that buffers partial network chunks until newline boundaries and emits strongly typed directive events (SAY, LATEX, PLOT, DIAGRAM, CLEAR, CTRL), plus a fallback regex math-to-speech sanitizer on every SAY line.

**Required Behaviors & Edge Cases:**

- Preserve raw backslashes inside LATEX: lines verbatim without JSON decoding so \bar, \frac, \text, \nu, and \rho are never corrupted into control characters.
- Handle malformed or unprefixed lines gracefully (defaulting plain prose to SAY: while stripping accidental inline $ delimiters before TTS).
- Keep static system prompt prefixes byte-identical across turns to maximize Groq prompt caching (exempt from rate limits) and Gemini 3.8 Flash free context caching.

**Verification Gates:**

- Unit test feeding arbitrary 3-character streaming chunks proves all LaTeX backslash commands survive byte-for-byte with zero corruption and zero stray markup leaking into SAY: events.
- Fault-injection test simulating 429 rate-limit exhaustion across all three Groq model buckets seamlessly fails over to Gemini Flash with zero dropped turns.

### Phase 4: Explicit Pedagogical FSM & Chapter-Scoped Teaching Engine

**Goal & Dependency:** Turn the LLM router and scoped RAG store into a disciplined professor that teaches linearly, checks understanding, handles deep counter-questioning, and resumes cleanly. Depends on Phases 2 and 3.

**Modules to Build:**

- Explicit 5-state Python FSM (apps/api/tutor/fsm.py) implementing ONBOARDING, TEACH_STEP, MICRO_CHECK, INTERRUPT_QA, and RECAP, persisting current state, current_node_path, active_turn_id, and resume_stack directly to tutor_sessions JSONB on every transition.
- Hard 4,000-Token Prompt Budget Assembler enforcing exact per-section ceilings: static cached system prefix (~750 tokens), active subtopic brief (~500 tokens), top-3 ltree-fenced RAG chunks (~900 tokens, truncated at 300 tokens each), semantic whiteboard summary (~300 tokens), rolling 6-turn verbatim window plus 150-token running summary (~1,000 tokens), and concise 30–45 second completion budget (~550 tokens).
- Scope Guardrail Policy handling off-chapter questions with a brief acknowledgment and polite deferral unless the student explicitly confirms a chapter switch.
- Headless CLI Text Simulation Harness driving full chapter walkthroughs, simulated mid-step interruptions, and multi-turn counter-questions without needing audio or browser UI.

**Required Behaviors & Edge Cases:**

- When INTERRUPT_QA is entered, push the exact unplayed subpoints and unrendered board operations onto resume_stack; allow unlimited nested follow-up questions until the student confirms understanding, then pop the stack and generate a natural bridging sentence back to the paused step.
- In MICRO_CHECK, if the student answers incorrectly or expresses confusion, transition back to TEACH_STEP with a remedial-analogy flag rather than advancing order_index.

**Verification Gates:**

- Automated CLI test completes all subtopics of Chapter 1 in sequence, politely defers an injected Chapter 10 question, resolves a 3-turn counter-question chain inside INTERRUPT_QA, resumes the exact paused subpoint, and produces zero raw LaTeX inside SAY: outputs.

### Phase 5: LiveKit Voice Transport, Server Kokoro TTS & Two-Stage Barge-In

**Goal & Dependency:** Deliver full-duplex, echo-free voice conversation over laptop speakers with zero headphones and backchannel-safe interruption. Depends on Phase 4.

**Modules to Build:**

- FastAPI LiveKit token endpoint minting short-lived room JWTs bound to a verified tutor_session_id.
- Python LiveKit Agent Worker subscribing to the student's WebRTC microphone track and running local CPU Silero VAD.
- Server-side kokoro-onnx (int8) TTS streamer converting SAY: sentences incrementally into 24kHz mono PCM frames published solely as a LiveKit remote AudioTrack. Pre-synthesize and cache 3–4 short neutral filler clips (segment_id: "filler") in memory at worker startup, and prepend a mandatory 150ms digital-silence frame before every turn.
- Two-Stage Barge-In Controller:
  - Stage 1 (Soft Duck): Sustained speech over 200ms at an elevated confidence gate while the teacher is speaking emits PLAYOUT_PAUSE, mutes client audio, freezes the client board clock, and pauses pumping Kokoro PCM without canceling the active LLM task or clearing queued board operations.
  - STT & Guard: Transcribes the short student utterance via Groq whisper-large-v3-turbo (with local faster-whisper offline fallback) and passes it through the Backchannel & Whisper Hallucination Guard (filtering "okay", "uh-huh", "got it", "haan", "theek hai", empty/single-character transcripts, high no-speech probability, low average log-probability, and classic Whisper silence hallucinations such as "Thank you.", "You", "Bye").
  - Resume Path: On backchannel or room noise, rewinds Kokoro's PCM read cursor by 200ms (or to the previous clause boundary) and emits PLAYOUT_RESUME with the exact rewind_ms.
  - Stage 2 (Hard Commit): On a real question, increments active_turn_id, cancels in-flight LLM/TTS tasks within 50ms, broadcasts INTERRUPT_FLUSH, pushes unplayed text and unrendered board ops onto resume_stack, and routes into INTERRUPT_QA.
- Minimal Next.js Classroom Audio Shell capturing mic audio with echoCancellation, noiseSuppression, and autoGainControl enabled, and playing the remote track strictly through a live HTML audio element (autoplay, playsInline).
- Latency Masking Trigger sending AVATAR_CUE: thinking immediately upon VAD end-of-speech and playing a cached "filler" clip if real TTS synthesis exceeds 1,100ms.

**Required Behaviors & Edge Cases:**

- Never route audible playback through Web Audio API nodes; keep audible output strictly on the HTML audio element so Chromium and Safari WebRTC AEC reference mixers cancel speaker output cleanly.
- Log actual VAD energy distribution and tuned thresholds to .agents/DECISIONS.md after room-acoustic calibration.

**Verification Gates:**

- Live 10-minute session over laptop speakers (no headphones) produces zero self-interruption echo loops.
- Saying "okay", "haan", or coughing mid-sentence ducks briefly and resumes seamlessly with zero clipped or missing half-words.
- Asking a real question halts teacher audio in under 200ms and delivers a contextual spoken answer in approximately 1.4–2.0 seconds (with thinking/filler cues covering complex turns).

### Phase 6: Excalidraw Native-SVG Whiteboard, Spatial Allocator & Circle-to-Ask

**Goal & Dependency:** Render crisp, zero-overlap equations and graphs directly inside Excalidraw and allow students to point to confusing steps visually. Depends on Phase 4 (can be tested alongside or immediately after Phase 5).

**Modules to Build:**

- Backend Spatial Layout Allocator (apps/api/board/allocator.py) managing the virtual 1280×720 canvas across four non-overlapping zones (header, derivation, visual, callout), estimating bounding heights per LaTeX expression, tracking occupied rectangles, and emitting CLEAR_SLIDE when vertical capacity fills.
- Client-side MathJax 3 (mathjax-full tex2svg with font caching disabled) compiler and function-plot SVG generator creating standalone, self-contained Light Mode pure-vector SVGs with explicit pixel dimensions and zero external font URLs.
- Excalidraw Classroom Workspace (apps/web/src/components/classroom) injecting compiled SVGs as native Excalidraw image elements via addFiles and updateScene, tagging every element with customData (op_id, label, raw LaTeX/expression), and providing a bottom slide-history strip to revisit archived slides.
- Circle-to-Ask Geometry Matcher listening for student freehand strokes or arrows, computing client-side bounding-box overlap against injected Excalidraw elements, highlighting the matched equation, and emitting BOARD_SELECTION over the DataChannel so the next LLM turn knows the exact formula referenced without any screenshot vision API call.

**Required Behaviors & Edge Cases:**

- Serialize the whiteboard's semantic summary (active labels and LaTeX strings only — never raw Excalidraw scene JSON) back into the 300-token whiteboard prompt budget slot.
- Ensure every injected SVG has transparent or Light Mode crisp contrast and fixed aspect ratios so Excalidraw never squashes tall fractions or wide integrals.

**Verification Gates:**

- A 5-step mathematical derivation alongside a plotted probability curve renders with zero overlapping elements and stays razor-sharp at 300% zoom in both Chromium and Safari with zero external font network requests in DevTools.
- Panning and zooming exhibit zero drift; circling Step 2 and asking "What does this symbol mean?" causes the teacher to address Step 2 specifically.

### Phase 7: Sample-Accurate Playout Clock Sync & Barge-In Rollback

**Goal & Dependency:** Synchronize whiteboard reveals tightly to spoken audio and guarantee interrupted turns never leak future steps onto the board. Depends on Phases 5 and 6.

**Modules to Build:**

- Server PCM Offset Stamper inside the Kokoro worker tracking cumulative 24kHz PCM samples per turn_id, computing exact playout_offset_ms for every LATEX, PLOT, DIAGRAM, and CLEAR directive at the instant it appears in the stream, sending BOARD_SCHEDULE ahead of audio frames, and emitting AUDIO_SEGMENT_START ("filler" or "response") as the first real PCM frame enters LiveKit.
- Client Playout Clock Controller establishing the unconditional silent Web Audio tap (remote MediaStream into audio worklet/analyser terminated through a zero-gain node into the audio context destination) so neither Chromium nor Safari suspends processing.
- Arm-Gated RMS Onset Detector that ignores "filler" segments, arms strictly upon receiving AUDIO_SEGMENT_START with segment_id: "response", anchors turn start time on the first non-silent PCM frame, freezes elapsed time on PLAYOUT_PAUSE, shifts elapsed time backward by rewind_ms on PLAYOUT_RESUME, and releases queued BoardOp items on the exact requestAnimationFrame where elapsed time reaches playout_offset_ms.
- Epoch & Deduplication Guard rejecting any packet whose turn_id is below active_turn_id, preventing duplicate injection by op_id, and reconciling unrendered operations cleanly with the server's resume_stack.
- Toggleable Dev Telemetry HUD displaying active turn_id, playout elapsed_ms, VAD state, active LLM bucket, remaining Groq TPM, and per-stage latency timings.

**Required Behaviors & Edge Cases:**

- Handle late DataChannel packets defensively: if a BoardOp arrives after its playout_offset_ms has already passed for the current active turn_id, inject it immediately rather than dropping it.
- When a student interrupts at Step 1, confirm the client discards Steps 2–4 immediately and reports the last rendered op_id (or server infers it from paused playout time) so resume_stack re-schedules only unrendered steps upon return.

**Verification Gates:**

- Formulas appear within ±150ms of the teacher speaking them, including on turns preceded by a cached "filler" clip.
- Interrupting during Step 1 prevents Steps 2–4 from ever flashing on screen, and resuming after Q&A draws Steps 2–4 in exact order.

### Phase 8: TalkingHead 3D Avatar & GPU FLIP Full-to-PiP Layout Engine

**Goal & Dependency:** Add the lip-synced 3D AI teacher with flicker-free, thermal-safe transitions between Full Screen and the 200×200px top-right PiP whiteboard corner. Depends on Phase 7.

**Modules to Build:**

- Isolated AvatarStage React Client Component wrapping met4citizen/TalkingHead (v1.8.2, Three.js r186), loading the local Meshopt-compressed .glb model, capping the render loop strictly at 30fps globally, and invoking head.dispose() on route unmount.
- HeadAudio AudioWorklet integration plugged directly into Phase 7's existing unconditional silent zero-gain Web Audio tap so visemes track the exact played LiveKit audio without disturbing hardware AEC.
- GPU FLIP Layout Controller keeping the WebGL canvas mounted permanently at root level; switching between FULL_AVATAR and PIP_WHITEBOARD animates solely transform (translate3d and scale) and clip-path over ~280ms, calling Three.js renderer setSize and subtle head-and-shoulders camera reframing once on transitionend.
- Manual Layout Pin/Unpin Control emitting LAYOUT_OVERRIDE so students can force Full Avatar, PiP Whiteboard, or Automatic mode anytime.
- Avatar Expression Mapper translating AVATAR_CUE events (listening, thinking, speaking, idle) into subtle eye contact, head tilt, nodding, and breathing animations.

**Required Behaviors & Edge Cases:**

- Re-compute FLIP transform targets cleanly on browser window resize without tearing down the WebGL context.
- Keep PiP z-index cleanly layered over Excalidraw without intercepting canvas pointer events outside its 200×200px rounded bounding box.

**Verification Gates:**

- Running 50 rapid Full-to-PiP and PiP-to-Full toggles exhibits zero WebGL context loss, zero canvas stretching, accurate audio-locked lip-sync, and flat heap memory in Chrome DevTools.
- Sustained CPU utilization on a non-CUDA laptop stays near 25–35% with fan acoustics quiet enough to avoid false Silero VAD triggers.

### Phase 9: Session Persistence, Interactive Replay & Exam Study Exports

**Goal & Dependency:** Turn every live tutoring session into permanent, reload-proof study assets for exam preparation. Depends on Phase 8.

**Modules to Build:**

- Turn-Boundary Snapshot Persistence writing the Excalidraw slide deck snapshot and FSM cursor to tutor_sessions after every completed turn, plus appending structured records to session_events.
- Reload Recovery Flow restoring the exact active slide, archived slide strip, active chapter lock, and FSM subtopic cursor upon browser refresh or reopening an in-progress session.
- Interactive Timeline Replayer allowing students to scrub through session_events directly on Excalidraw and copy clean raw LaTeX strings from any formula on the board.
- One-Click Study Exporter generating a clean, printable Markdown/PDF chapter cheat sheet compiling all board formulas and every misconception cleared during INTERRUPT_QA loops, plus an optional client-side MediaRecorder WebM export at zero server cost.
- Course Mastery Dashboard displaying chapter completion progress per course and highlighting weak subtopics flagged by frequent INTERRUPT_QA loops.

**Required Behaviors & Edge Cases:**

- Keep Excalidraw scene snapshots compact by storing canonical BoardOp payloads and regenerating SVG data URLs on hydration rather than bloating Postgres JSONB with repeated SVG blobs.

**Verification Gates:**

- Hard-refreshing the browser mid-chapter restores the exact whiteboard state and resumes from the correct subtopic without repeating already-taught steps.
- Exporting a completed 15-minute chapter session produces an accurate formula cheat sheet and a smoothly scrubbable interactive replay.

### Phase 10: Soak Testing, Chaos Validation & $0 Deployment Hardening

**Goal & Dependency:** Prove long-session stability, free-tier resilience, and zero-cost hosting reliability before daily academic use. Depends on Phase 9.

**Modules to Build:**

- End-to-End Latency & Memory Instrumentation recording P50/P95 spans across VAD end, STT, LLM TTFT, TTS first byte, and client audio start, plus a 45-minute soak test script and Chrome heap/WebGL buffer checklist.
- Chaos & Failover Test Suite simulating mid-lecture Groq 429 exhaustion across all three model buckets, transient network disconnects, and LiveKit reconnection recovery.
- Supabase Free-Tier Operational Safeguards: scheduled weekly GitHub Actions keep-alive health check (preventing 7-day inactivity auto-pause) and an automated weekly logical export backing up courses, syllabus_nodes, and session_events.
- Zero-Cost Deployment Manifests targeting Vercel Hobby (apps/web), Supabase Free Tier (PostgreSQL), LiveKit Cloud Build Free (WebRTC media), and either local execution (unlimited personal study) or Oracle Cloud Always Free ARM VM / Hugging Face Spaces (apps/api + Kokoro worker).

**Required Behaviors & Edge Cases:**

- Verify all secrets live strictly in platform environment variables and never leak into Next.js client bundles.
- Confirm offline Ollama fallback engages cleanly if internet access drops mid-session without crashing the FastAPI worker.

**Verification Gates:**

- A continuous 45-minute study session of a real university chapter completes with zero crashes, zero WebGL or AudioWorklet memory growth, zero false fan-noise VAD loops, verified failover under forced 429 injection, and $0 API spend.

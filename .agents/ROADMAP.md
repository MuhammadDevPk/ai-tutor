# AI Tutor — Roadmap (harness)

> Extracted verbatim from IMPLEMENTATION-PLAN.md, Sections 4 and 6.
> Execute one phase at a time. A phase is done only when every one of its Verification Gates passes.

## 4. Complete 10-Phase Implementation Plan (AI-Agent Execution Spec)

Hand your AI coding tool one phase at a time, requiring it to pass every Verification Gate before starting the next phase.

### Phase 1: Repository Scaffold, .agents/ Harness & Single-Owner Schema

**Scope:** Establish the monorepo structure, agent guardrails, Supabase PostgreSQL schema, and automated OpenAPI contract sync.

**Deliverables:**

- Create pnpm monorepo with apps/web (Next.js 16, React 19, Tailwind Light Mode) and apps/api (Python 3.11+ uv, FastAPI, Alembic, psycopg3).
- Write .agents/ARCHITECTURE.md and .agents/PATTERNS.md containing Sections 1–3 of this plan verbatim so every future AI coding session obeys all seven invariants and the Do-Not-Build list.
- Provision Supabase PostgreSQL Free Tier and run Alembic migration 001 enabling vector and ltree extensions plus all five core tables and GiST/HNSW indexes.
- Define Pydantic v2 schemas for all REST endpoints and DataChannel wire events in apps/api, and configure openapi-typescript to generate strongly typed frontend clients into apps/web.
- Implement lightweight auth/session protection and course CRUD endpoints.

**Verification Gates:**

- Next.js and FastAPI boot locally with zero Docker Postgres or Redis containers running.
- Database integration test confirms ltree ancestor filtering isolates Chapter 1 from Chapter 2 with zero leakage.
- Modifying a Pydantic schema updates frontend TypeScript types via a single pnpm script with zero compile errors.

### Phase 2: Math-Aware PDF Ingestion & Scoped RAG Pipeline

**Scope:** Transform raw university PDF handouts (math, statistics, physics) into structured, formula-intact syllabus trees and chapter-fenced embeddings.

**Deliverables:**

- Build an async FastAPI ingestion pipeline using PyMuPDF4LLM or Docling to extract clean Markdown and intact LaTeX equations.
- Add a selective fallback routing only scanned or broken-formula pages to gemini-3.8-flash Vision (free tier) for clean LaTeX recovery.
- Build a Curriculum Tree Extractor using gemini-3.8-flash (long-context free tier) on extracted headings/Table of Contents to populate syllabus_nodes (ltree paths, learning objectives, and <=250-token summaries).
- Build a Formula-Preserving Chunker that never crosses subtopic boundaries or splits display math blocks, generates 384-dim embeddings locally via fastembed (BAAI/bge-small-en-v1.5), and bulk-inserts into Supabase document_chunks.
- Build the Light Mode Course & Syllabus Inspector UI in Next.js supporting PDF upload, ingestion status tracking, manual heading edits, and a "Start Chapter" button.

**Verification Gates:**

- Uploading a real multi-chapter university handout renders an accurate hierarchical syllabus tree with readable math previews.
- Automated retrieval test locked to Chapter 1 returns 0 chunks from Chapters 2+ even on queries containing strong keywords from later chapters.

### Phase 3: Model-Bucket LLM Router & Line-Delimited Stream Parser

**Scope:** Build the rate-limit-resilient multi-provider inference engine and zero-escape streaming directive parser.

**Deliverables:**

- Build an in-process Python ModelBucketRouter that parses Groq's x-ratelimit-remaining-tokens, x-ratelimit-remaining-requests, and x-ratelimit-reset-tokens headers after every call.
- Configure single-key model-bucket rotation across openai/gpt-oss-20b (~1,000 tok/s), openai/gpt-oss-120b (~500 tok/s), and qwen/qwen3.8-27b (~450 tok/s), proactively rotating buckets whenever remaining TPM drops below 4,500 — before hitting HTTP 429.
- Configure automatic cross-provider failover to gemini-3.8-flash / gemini-3.5-flash-lite (free tier) on Groq exhaustion or circuit-breaker trip, and to local Ollama only when cloud endpoints are unreachable.
- Add an in-process cachetools LRU cache for recurring foundational concept definitions.
- Implement the Line-Delimited Stream Parser splitting incremental token chunks into SAY:, LATEX:, PLOT:, DIAGRAM:, CLEAR:, and CTRL: directives, paired with a regex math-to-speech fallback sanitizer on SAY: lines.

**Verification Gates:**

- Unit test streaming arbitrary 3-character chunks proves \bar, \frac, \text, \nu, and \rho pass through byte-for-byte with zero control-character corruption.
- Fault-injection test simulating 429 errors across Groq buckets fails over seamlessly to Gemini Flash with zero dropped turns.

### Phase 4: Explicit Pedagogical FSM & Chapter-Scoped Teaching Engine

**Scope:** Build the ~150-line stateful teacher controller enforcing linear chapter progression, Socratic micro-checks, and interrupt-and-resume tutoring.

**Deliverables:**

- Implement the 5-state Python FSM (ONBOARDING, TEACH_STEP, MICRO_CHECK, INTERRUPT_QA, RECAP) persisting transitions and resume_stack snapshots directly to tutor_sessions JSONB.
- Implement the Token Budget Assembler strictly capping each turn at <=4,000 tokens with a static cached prefix (leveraging Groq prompt caching and Gemini 3.8 Flash free context caching).
- Implement the Scope Guardrail Policy instructing the tutor to acknowledge and politely defer off-chapter questions unless the student triggers an explicit chapter switch.
- Build a headless CLI simulation harness to test full text-mode chapters before connecting audio.

**Verification Gates:**

- Automated CLI simulation walks through all subtopics of Chapter 1 in order, politely defers an injected Chapter 10 question, resolves a 3-turn counter-question chain inside INTERRUPT_QA, resumes the exact paused subpoint, and emits zero raw LaTeX inside SAY: lines.

### Phase 5: LiveKit Voice Transport, Server Kokoro TTS & Two-Stage Barge-In

**Scope:** Stand up real-time full-duplex audio with hardware AEC over laptop speakers and backchannel-safe interruption.

**Deliverables:**

- Build FastAPI endpoint minting scoped LiveKit room JWTs bound to tutor_session_id.
- Stand up the Python LiveKit Agent Worker subscribing to the student's WebRTC audio track and running local Silero VAD on CPU.
- Integrate server-side kokoro-onnx (int8) synthesizing SAY: lines sentence-by-sentence into 24kHz mono PCM streamed over a LiveKit remote AudioTrack, prepending a 150ms digital-silence lead-in per turn and pre-caching 3–4 short neutral filler clips (segment_id: "filler").
- Wire Groq whisper-large-v3-turbo STT (with local faster-whisper offline fallback) into the Two-Stage Barge-In Controller and the Backchannel & Whisper Hallucination Guard, including the 200ms PCM cursor rewind on PLAYOUT_RESUME.
- Build the minimal Next.js classroom audio shell wiring the remote track strictly to `<audio autoplay playsInline>` with browser echoCancellation, noiseSuppression, and autoGainControl enabled.

**Verification Gates:**

- Live 10-minute test over laptop speakers (no headphones) exhibits zero self-interruption feedback loops.
- Saying "okay", "haan", or coughing during a sentence ducks briefly and resumes cleanly with zero clipped words.
- Asking a real question stops teacher audio in <200ms, plays a thinking/filler cue if needed, answers accurately within ~1.4–2.0s, and resumes the interrupted lesson upon confirmation.

### Phase 6: Excalidraw Native-SVG Whiteboard, Spatial Allocator & Circle-to-Ask

**Scope:** Render crisp, collision-free math equations and function plots natively inside Excalidraw and let students visually point to confusing steps.

**Deliverables:**

- Implement the backend Spatial Layout Allocator managing the four virtual 1280×720 zones (header, derivation, visual, callout), formula height estimation, and automatic CLEAR_SLIDE pagination.
- Build the client-side MathJax 3 (mathjax-full tex2svg, fontCache: "none") compiler and function-plot SVG generator producing self-contained Light Mode SVGs with explicit pixel dimensions.
- Build the Excalidraw Classroom Canvas injecting compiled SVGs natively as image elements tagged with customData (op_id, label, raw LaTeX/expression), plus a bottom slide-history strip for viewing prior slides.
- Implement Circle-to-Ask Geometry Matching: when the student draws a loop or arrow overlapping an injected element, compute bounding-box intersection client-side and emit BOARD_SELECTION over the DataChannel.

**Verification Gates:**

- A 5-step derivation plus plotted curve renders with zero overlapping boxes and remains razor-sharp at 300% zoom in both Chromium and Safari with zero external font network requests.
- Panning and zooming produce zero element drift; circling Step 2 and asking "Why does this term appear?" causes the teacher to explain Step 2 specifically.

### Phase 7: Sample-Accurate Playout Clock Sync & Barge-In Rollback

**Scope:** Lock whiteboard appearance tightly to spoken audio and prevent interrupted turns from flashing future steps on screen.

**Deliverables:**

- Instrument the server Kokoro pipeline to track exact cumulative 24kHz PCM samples per turn_id, stamping playout_offset_ms onto each BoardOp and emitting AUDIO_SEGMENT_START as the first real PCM frame enters LiveKit.
- Build the client Playout Clock Controller: unconditional silent Web Audio tap (MediaStreamAudioSourceNode -> Analyser/Worklet -> GainNode(0) -> destination), arm-gated RMS onset detector ignoring "filler" segments, pause/rewind delta accounting, op_id deduplication, and turn_id epoch filtering.
- Build a toggleable Dev Telemetry HUD displaying live turn_id, elapsed_ms, VAD state, active Groq/Gemini model bucket, remaining TPM, and stage-by-stage latency.

**Verification Gates:**

- Formulas appear within ±150ms of the teacher speaking them, even when a cached filler precedes the main answer.
- Interrupting during Step 1 halts Steps 2–4 cleanly with zero ghost elements flashing onto the board, and renders them accurately once the lesson resumes.

### Phase 8: TalkingHead 3D Avatar & GPU FLIP Full-to-PiP Layout Engine

**Scope:** Add an expressive, lip-synced 3D teacher that transitions smoothly between Full Screen and a 200×200px top-right PiP corner without WebGL glitches or loud laptop fans.

**Deliverables:**

- Host one compressed Mixamo-rigged teacher .glb model with ARKit/Oculus viseme blend shapes under apps/web/public/avatars/ (Meshopt-compressed for fast load).
- Wrap met4citizen/TalkingHead (v1.8.2) in an isolated client component locked to 30fps globally, calling head.dispose() cleanly on route exit.
- Insert the HeadAudio AudioWorklet into the existing unconditional silent zero-gain Web Audio tap so lip-sync locks to the remote audio track without breaking hardware AEC.
- Build the GPU FLIP Layout Controller: keeps the WebGL canvas permanently mounted; animates Full ↔ 200×200px top-right PiP exclusively via transform and clip-path, running Three.js renderer sizing and camera reframing once on transitionend. Include a manual layout pin/unpin toggle.
- Map AVATAR_CUE events (listening, thinking, speaking, idle) to subtle head nods, eye contact, and breathing animations.

**Verification Gates:**

- 50 rapid Full ↔ PiP transitions show zero WebGL context loss, zero canvas stretching, synchronized lip-sync, and flat browser heap memory.
- Sustained laptop CPU stays around 25–35% with fans quiet enough to avoid Silero VAD false triggers.

### Phase 9: Session Persistence, Interactive Replay & Exam Study Exports

**Scope:** Turn every live tutoring session into durable revision material and protect against browser reloads.

**Deliverables:**

- Persist Excalidraw scene snapshots and FSM state on every completed turn so refreshing or reopening a chapter restores the exact slide and subtopic cursor.
- Build the Interactive Session Replayer that scrubs session_events directly on Excalidraw so you can replay any past lecture and copy clean LaTeX formulas.
- Build One-Click Study Exports: printable Markdown/PDF chapter cheat sheet compiling all whiteboard formulas plus Q&A misconceptions cleared during the session, and optional client-side MediaRecorder WebM video export at $0 server cost.
- Build a Course Mastery Dashboard showing chapter completion across courses and flagging weak topics with high interruption frequency.

**Verification Gates:**

- Hard-refreshing the browser mid-chapter restores the exact whiteboard slide and resumes from the correct subtopic without repeating completed material.
- Exporting a completed 15-minute session produces a clean printable formula cheat sheet and a working interactive replay.

### Phase 10: Soak Testing, Chaos Validation & $0 Deployment Hardening

**Scope:** Validate thermal stability, free-tier resilience, and long-term operational reliability before daily academic use.

**Deliverables:**

- 45-Minute Continuous Soak Test: Study an entire real chapter end-to-end while profiling Chrome WebGL/AudioWorklet memory, end-to-end P50/P95 latency, and local CPU/fan behavior.
- Chaos & Failover Drill: Intentionally trigger Groq 429 errors mid-lecture, simulate network drops, and verify clean bucket rotation and Gemini Flash failover without dropping the session.
- Supabase Free-Tier Safeguards: Because Supabase Free Tier pauses projects after 1 week of inactivity and includes no automatic backups, add a lightweight scheduled GitHub Actions keep-alive ping + weekly logical backup export of courses, syllabus_nodes, and session_events.
- Zero-Cost Deployment Configuration: Prepare deployment manifests for Vercel Hobby (apps/web), Supabase Free Tier (DB), LiveKit Cloud Build Free (media), and either local execution (unlimited personal study) or an Oracle Cloud Always Free ARM VM / Hugging Face Spaces (apps/api + Kokoro worker).

**Verification Gates:**

- Full 45-minute session completes with zero crashes, zero WebGL leaks, zero paid API charges, and verified failover under forced rate-limit exhaustion.

## 6. Realistic Execution Timeline (AI-Native Workflow)

- **Milestone 1 — Voice + Scoped Syllabus Study MVP (Phases 1–5): ~4–5 Weeks.** Upload your handouts, lock strictly to Chapter 1, hold real-time speaker-based voice conversations with two-stage barge-in, and never hit free-tier outages.
- **Milestone 2 — Synchronized Math Whiteboard + 3D PiP Teacher (Phases 6–8): ~3 Weeks.** Adds collision-free Excalidraw MathJax/function plots, circle-to-ask pointing, sample-accurate audio sync, and the 30fps TalkingHead FLIP PiP teacher.
- **Milestone 3 — Replay, Cheat Sheets & Hardening (Phases 9–10): ~1–2 Weeks.** Adds reload resilience, interactive lecture scrubbing, printable exam formula sheets, soak testing, and $0 cloud deployment.

# AI Tutor — Complete Implementation Plan

> Saved from Malik's plan, 23 November 2026. This is the master plan document.
> Per the plan, its content is structured to drop into the repository's `.agents/`
> harness files (ARCHITECTURE.md, PATTERNS.md, ROADMAP.md) during Phase 1.
> No code is written by hand from this document; the AI coding agent executes it phase by phase.

## 1. System Architecture & Zero-Cost Technology Stack

This specification is structured as a code-free, Staff-level architectural blueprint designed to drop directly into your repository's .agents/ harness files (ARCHITECTURE.md, PATTERNS.md, and ROADMAP.md) so an AI coding agent can execute each phase cleanly without architectural drift.

To keep operating costs strictly at $0, the platform never renders video on a server. Instead, the backend streams lightweight audio and structured whiteboard directives over WebRTC, while the student's browser renders both the 3D teacher (WebGL) and crisp mathematical whiteboard (SVG/Canvas) locally.

### Core Component Topology (8 Moving Parts)

| Layer | Approved Choice | System Owner | Verified $0 Free-Tier Allowances & Architectural Rationale |
|---|---|---|---|
| Frontend Workspace | Next.js 16 (App Router), React 19, Tailwind CSS (Light Mode), pnpm | Web App | Pure UI, classroom layout, Excalidraw board, WebGL avatar, and WebRTC client. Keeps Light Mode clean and avoids heavy backdrop-filter blur over WebGL/Canvas layers to prevent GPU compositing stalls. |
| Backend & Voice Worker | Python 3.11+, FastAPI, LiveKit Agents Worker, uv, Alembic, psycopg3 | Single Backend | Sole owner of database migrations, reads/writes, PDF ingestion, pedagogical FSM, LLM routing, rate limiting, Kokoro TTS synthesis, and spatial whiteboard layout. |
| Database & Vectors | Supabase PostgreSQL Free Tier (pgvector + ltree) | Backend Only | 500 MB database per project (up to 2 active projects), 1 GB file storage, 5 GB egress plus 5 GB cached egress, and 50,000 monthly active users. Offloads Postgres CPU/RAM off your laptop to keep fans quiet during voice sessions. |
| Media Transport | LiveKit (Local livekit-server binary for unlimited dev; LiveKit Cloud Build Free for hosting) | Shared | Cloud Build includes 5,000 WebRTC participant minutes/month, 1,000 hosted agent session minutes/month, 50 GB downstream transfer, and 100 concurrent participants. Provides hardware Acoustic Echo Cancellation (AEC) and ordered DataChannels. |
| 3D Avatar Engine | met4citizen/TalkingHead (v1.8.2, Three.js r186) + local Mixamo/ARKit .glb + HeadAudio | Web App | Supports Meshopt compression, automatic skeleton retargeting, head.dispose() memory cleanup, and local .glb loading after defunct Ready Player Me URLs were removed. Capped at 30fps globally to prevent thermal throttling. |
| Whiteboard Engine | Excalidraw (MIT) + MathJax 3 (mathjax-full tex2svg) + function-plot | Web App | Renders LaTeX and function plots into self-contained pure-vector SVGs injected natively as Excalidraw image elements — zero pan/zoom drift, zero external font dependencies, and MIT-licensed forever. |
| Voice AI Pipeline | Silero VAD (local CPU ONNX) + Groq whisper-large-v3-turbo (STT) + Server kokoro-onnx int8 (TTS) | Backend | Groq Whisper free tier allows 20 RPM, 2,000 RPD, 7,200 audio seconds/hour, and 28,800 audio seconds/day (~8 hours of student speech daily). Server-side Kokoro runs faster than real-time on CPU and preserves browser WebRTC AEC. |
| LLM Inference Waterfall | Tier 1: Groq single-key model-bucket rotation (openai/gpt-oss-20b, openai/gpt-oss-120b, qwen/qwen3.8-27b) → Tier 2: Google AI Studio (gemini-3.8-flash, gemini-3.5-flash-lite) → Tier 3: Local Ollama (offline fallback only) | Backend | Each Groq free model bucket provides 30 RPM, 1,000 RPD, 8,000 TPM, and 200,000 TPD, with cached prompt tokens excluded from rate limits. Note that llama-3.1-8b-instant and llama-3.3-70b-versatile moved to Enterprise on August 16, 2026 and must not be targeted. Gemini 3.8 Flash and 3.5 Flash-Lite remain free without a billing card, with free context caching on 3.8 Flash. |

### Anti-Drift Guardrails (Mandatory Do-Not-Build List for Your AI Agent)

Enforce these rules explicitly in .agents/PATTERNS.md so the coding agent never reintroduces broken dependencies or bloat:

- **No Ready Player Me URLs or SDKs:** Use exclusively self-hosted .glb avatars stored in the frontend public directory.
- **No Browser-Side TTS (HeadTTS):** Locally synthesized Web Audio bypasses browser WebRTC hardware AEC and causes continuous speaker-to-mic self-interruption.
- **No KaTeX for Whiteboard SVG Injection:** KaTeX generates HTML/CSS backed by external WOFF2 font files, which browser security sandboxes block inside data:image/svg+xml canvas injections. Lock strictly to MathJax 3 tex2svg with font caching disabled so every SVG contains self-contained vector paths.
- **No tldraw 4.0:** Production deployments require commercial licensing or watermarks; use MIT-licensed Excalidraw exclusively.
- **No Redis, No LangGraph, No Dual ORMs:** In-process Python sliding-window token buckets, an in-memory LRU cache (cachetools), and an explicit ~150-line Python Finite State Machine (FSM) eliminate three unnecessary infrastructure layers. FastAPI is the single database owner; Next.js never connects to Postgres directly and communicates only through generated OpenAPI TypeScript/Zod clients.
- **No JSON Tool Calling for Mid-Lecture Formulas:** Standard tool calling breaks mid-sentence synchronization (requiring extra round trips) and silently corrupts single-escaped LaTeX commands (\bar, \frac, \text, \nu, \rho) into JSON control characters.
- **No Multi-Key Groq Farming:** Groq rate limits are enforced per organization, not per key, and farming accounts violates Terms of Service. Rotate across distinct model buckets on one key and fail over cleanly to Gemini Flash.

## 2. Seven Non-Negotiable System Invariants

Every engineering decision across all 10 phases must uphold these invariants:

1. **Single-Path AEC-Safe Audio Graph:** All teacher audio is synthesized server-side via kokoro-onnx (24kHz mono PCM) and published exclusively as a LiveKit remote AudioTrack. On the client, audible output plays solely through a live `<audio autoplay playsInline>` element so browser hardware AEC cancels speaker output from the microphone without headphones. Lip-sync (HeadAudio AudioWorklet) and RMS onset detection tap the remote MediaStream via an isolated Web Audio graph terminated unconditionally through a zero-gain node into the audio context destination — ensuring neither Chromium nor Safari suspends or garbage-collects the worklet while keeping audio output strictly on the `<audio>` element.

2. **Sample-Accurate Shared Playout Clock:** Never sync whiteboard drawings using server wall-clock timestamps. Before every new spoken turn, the server inserts a mandatory 150ms digital-silence lead-in, emits an AUDIO_SEGMENT_START DataChannel event labeled as either "filler" or "response", and computes each whiteboard operation's playout_offset_ms strictly from Kokoro's exact cumulative generated PCM sample count. The client arms its RMS speech-onset detector only after receiving a "response" start event (never on cached fillers), anchors turn start time on the first non-silent frame, and fires queued whiteboard operations on the exact animation frame elapsed playout time reaches playout_offset_ms.

3. **Two-Stage Backchannel-Safe Barge-In:** When Silero VAD detects sustained student speech (>200ms at an elevated confidence gate while the teacher is speaking), the agent enters Stage 1 (Soft Duck): it emits PLAYOUT_PAUSE to mute client `<audio>` and freeze the client board clock, and pauses pumping Kokoro PCM frames without canceling the LLM stream or discarding queued board operations. Short-utterance STT then runs through a Backchannel & Whisper Hallucination Guard that filters natural acknowledgments ("okay", "uh-huh", "got it", "haan", "theek hai"), empty or single-character transcripts, high no-speech probability, low average log-probability, and known Whisper silence hallucinations ("Thank you.", "You", "Bye").
   - **Backchannel or Room Noise Path:** The server rewinds its Kokoro PCM read cursor by 200ms (or to the last clause boundary) so packets swallowed in transit while muted are never lost, emits PLAYOUT_RESUME with the exact rewind offset so the client shifts its board clock back identically, and resumes seamlessly.
   - **Real Question Path (Stage 2 Hard Commit):** The server increments the monotonic turn_id epoch, cancels active LLM/TTS tasks, broadcasts INTERRUPT_FLUSH, pushes unplayed sentences and unrendered whiteboard operations onto resume_stack, and transitions the FSM into INTERRUPT_QA. The client strictly drops any packet carrying a stale turn_id.

4. **Single-Pass Line-Delimited Streaming Protocol:** Rather than JSON tool calls, the LLM emits newline-delimited directives in one streaming pass: SAY: for pure spoken prose, LATEX: for raw unescaped mathematical formulas, PLOT: for mathematical functions and domains, DIAGRAM: for structured diagrams, CLEAR: for slide/layout transitions, and CTRL: for rare state transitions (such as advancing a subtopic). Every SAY: line passes through a fallback regex math-to-speech sanitizer and streams directly into Kokoro (advancing cumulative sample count), while every visual directive immediately locks onto the exact PCM offset reached at that point in the monologue.

5. **GPU-Composited FLIP Avatar Transitions:** The 3D WebGL canvas stays mounted permanently at the root of the classroom viewport — never unmounted when switching between Full Screen and the 200×200px top-right Picture-in-Picture (PiP) corner. Layout transitions animate only GPU-composited transform (translate3d and scale) and clip-path over ~280ms so zero layout reflows or WebGL buffer reallocations happen mid-animation. Three.js renderer resizing and head-and-shoulders camera reframing execute once upon transitionend.

6. **Database-Enforced Curriculum Fencing (ltree):** Chapter discipline is enforced mathematically at the database layer rather than relying on prompt obedience. Every syllabus node and document chunk stores a PostgreSQL ltree path (for example, sta301.ch01.t02_mean). Every RAG vector retrieval applies a mandatory SQL ancestor constraint (syllabus_path <@ active_chapter_path), making cross-chapter leakage impossible.

7. **4,000-Token Per-Turn Cap & Honest Latency Masking:** To stay well under Groq's 8,000 TPM ceiling per model bucket, every prompt enforces strict token caps: static cached system prefix (~750 tokens, exempt from Groq rate-limit token counts), pre-summarized subtopic brief (~500 tokens), top-3 ltree-fenced RAG chunks (~900 tokens), semantic whiteboard summary (~300 tokens), rolling 6-turn memory + summary (~1,000 tokens), and concise 30–45 second reply (~550 tokens). Because batch Groq Whisper creates a realistic 1.4s–2.0s P50 voice-to-voice turnaround, the server immediately sends an AVATAR_CUE: thinking signal upon VAD end-of-speech and plays a pre-synthesized cached filler (segment_id: "filler") if real speech synthesis exceeds 1,100ms.

## 3. Data Model, Pedagogical FSM & Wire Contracts

### Database Schema Blueprint (Single Owner: FastAPI + Alembic)

- **courses:** Holds student owner ID, university/program context, course code (e.g., STA301, MTH5101), title, and baseline skill setting (e.g., foundational from scratch).
- **syllabus_nodes:** Stores the curriculum tree with a GiST-indexed ltree path, node type (chapter, topic, subtopic), sequential order_index, title, JSON learning objectives, key formulas list, compact <=250-token summary, and mastery_status (not_started, in_progress, mastered).
- **document_chunks:** Stores formula-preserving Markdown chunks bounded strictly within a single subtopic (syllabus_path), page number, extracted raw LaTeX blocks, and an HNSW-indexed 384-dimensional pgvector embedding generated locally via fastembed (BAAI/bge-small-en-v1.5).
- **tutor_sessions:** Stores active course reference, hard chapter lock (active_chapter_path), active subtopic cursor (current_node_path), current FSM state, monotonic active_turn_id, pacing/analogy preferences, JSONB resume_stack (paused lesson text + unrendered board ops), and latest Excalidraw scene snapshot for reload resilience.
- **session_events:** Append-only timeline recording session_id, turn_id, event_type (USER_SPEECH, AI_SAY, BOARD_OP, STATE_CHANGE), playout_offset_ms, and structured payload to power deterministic lecture replay and cheat-sheet exports.

### Explicit Pedagogical FSM (5 Deterministic States)

- **ONBOARDING:** Greets the student, confirms target chapter, checks prerequisite comfort level and pace, and locks active_chapter_path.
- **TEACH_STEP:** Teaches one atomic concept (30–45 seconds of voice + synchronized whiteboard formulas/plots) while tracking remaining subpoints in the active subtopic.
- **MICRO_CHECK:** Asks one targeted verification question before moving forward. If the student struggles, loops back into a simpler analogy or visual breakdown rather than skipping ahead.
- **INTERRUPT_QA:** Entered exclusively on Stage-2 hard barge-in. Preserves the paused lesson frame on resume_stack, handles unlimited follow-up counter-questions until the student confirms clarity, then pops resume_stack and bridges cleanly back to the exact interrupted concept. Politely defers off-chapter questions unless the student initiates an explicit chapter switch.
- **RECAP:** Summarizes the completed chapter's key formulas, updates mastery_status to mastered, and triggers revision sheet availability.

### Wire Protocol Catalog (LiveKit DataChannel)

**Server → Client Events:**

- **AUDIO_SEGMENT_START:** Fields turn_id, segment_id ("filler" | "response"). Arms client RMS clock strictly on "response".
- **BOARD_SCHEDULE:** Fields turn_id, layout_mode (FULL_AVATAR | PIP_WHITEBOARD), and list of BoardOp items (op_id, playout_offset_ms, action, zone, label, raw payload, optional domain, server-allocated bbox).
- **PLAYOUT_PAUSE:** Stage-1 soft-duck signal for turn_id.
- **PLAYOUT_RESUME:** Backchannel recovery carrying turn_id and rewind_ms (default 200ms).
- **INTERRUPT_FLUSH:** Stage-2 hard commit carrying new_turn_id; client discards all queued ops below new_turn_id.
- **AVATAR_CUE:** Immediate avatar state cue (listening, thinking, speaking, idle).

**Client → Server Events:**

- **BOARD_SELECTION:** Emitted when the student circles or selects an injected Excalidraw element; passes referenced_op_id, label, and raw LaTeX/payload directly into the next turn's prompt context.
- **LAYOUT_OVERRIDE:** Manual user override switching between FULL_AVATAR, PIP_WHITEBOARD, or AUTO.

### Spatial Whiteboard Allocator Rules

The backend maintains a virtual 1280×720 canvas divided into four collision-free zones so the LLM never invents coordinates:

- **header:** Top banner showing the active subtopic heading and concept name.
- **derivation:** Left vertical auto-flow column that tracks exact line-height estimates and stacks formula steps with fixed margins.
- **visual:** Right panel reserved for plotted functions and conceptual diagrams.
- **callout:** Bottom highlight strip for boxed final equations or key intuition takeaways.

**Auto-Pagination:** When either main zone approaches vertical capacity, the allocator emits a CLEAR_SLIDE operation that archives the current Excalidraw slide into a bottom slide switcher and opens a fresh slide cleanly.

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

## 5. Bottleneck, Failure-Mode & Thermal Mitigation Matrix

| Failure Mode / Risk | Root Cause | Concrete Mitigation Built Into This Plan |
|---|---|---|
| Teacher self-interrupts over speakers | Browser-side TTS or Web Audio playback bypasses WebRTC AEC mixer. | Server-side Kokoro published exclusively as a LiveKit remote AudioTrack, played strictly via `<audio autoplay>`, with HeadAudio on a silent zero-gain tap. |
| Mid-lecture HTTP 429 outages | Groq's 8,000 TPM org-wide cap per model tripped by large RAG chunks. | Hard 4,000-token turn cap, static cached prompt prefix, header-driven rotation across 3 Groq model buckets, and automatic failover to Gemini 3.8 Flash / 3.5 Flash-Lite. |
| Broken or garbled formulas on board | JSON tool-calling corrupts \bar/\frac, or KaTeX fonts fail inside SVG data URIs. | Single-pass raw line-delimited LATEX: protocol + client-side MathJax 3 tex2svg with fontCache: "none" injected as pure vector paths. |
| Formulas pop up too early or late | Unsynchronized DataChannel vs. WebRTC Opus jitter buffer, or fillers shifting clocks. | Mandatory 150ms silence lead-in, AUDIO_SEGMENT_START gating ("filler" ignored), and exact server Kokoro PCM sample offsets matched to the client Web Audio clock. |
| Half-words lost after saying "okay" | In-flight UDP audio swallowed during Stage-1 soft-duck mute. | Two-stage barge-in with Whisper hallucination guard + 200ms Kokoro PCM read-cursor rewind and matched client clock shift on PLAYOUT_RESUME. |
| WebGL flicker/crash on PiP switch | Unmounting `<canvas>` or animating layout width/height triggers WebGL reallocations. | Single persistent WebGL canvas animated strictly via GPU FLIP (transform + clip-path), resizing Three.js once on transitionend. |
| Laptop fan noise triggers false VAD | Running Docker DB + Redis + Ollama + 60fps WebGL on a non-CUDA laptop. | Zero local DB/Redis containers (Supabase Free), Ollama stopped unless offline, 30fps global WebGL cap, int8 Kokoro ONNX, and Whisper silence/no-speech filtering. |
| Supabase database pauses mid-semester | Supabase Free Tier auto-pauses after 7 days of inactivity with no backups. | Scheduled weekly keep-alive health check + automated logical backup script in Phase 10. |

## 6. Realistic Execution Timeline (AI-Native Workflow)

- **Milestone 1 — Voice + Scoped Syllabus Study MVP (Phases 1–5): ~4–5 Weeks.** Upload your handouts, lock strictly to Chapter 1, hold real-time speaker-based voice conversations with two-stage barge-in, and never hit free-tier outages.
- **Milestone 2 — Synchronized Math Whiteboard + 3D PiP Teacher (Phases 6–8): ~3 Weeks.** Adds collision-free Excalidraw MathJax/function plots, circle-to-ask pointing, sample-accurate audio sync, and the 30fps TalkingHead FLIP PiP teacher.
- **Milestone 3 — Replay, Cheat Sheets & Hardening (Phases 9–10): ~1–2 Weeks.** Adds reload resilience, interactive lecture scrubbing, printable exam formula sheets, soak testing, and $0 cloud deployment.

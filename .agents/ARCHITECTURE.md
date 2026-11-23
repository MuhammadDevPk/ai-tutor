# ARCHITECTURE.md — AI Video Tutor Architecture (v2 plan, Sections 1–3)

## 1. Monorepo Layout & AI-Agent Operating Harness

Before Phase 1 begins, establish the directory structure and persistent agent context files so every new coding session inherits identical architectural constraints.

### Repository Topology

**`.agents/`** — Persistent context harness read by the coding agent at the start of every task:

- **ARCHITECTURE.md:** The 8-component topology, single-owner database rule, and all seven system invariants.
- **PATTERNS.md:** The mandatory Do-Not-Build list, line-delimited streaming protocol rules, Excalidraw SVG injection contract, and FLIP animation constraints.
- **ROADMAP.md:** Live tracker of Phases 1–10 with pass/fail checkboxes for each verification gate.
- **DECISIONS.md:** Append-only log of calibrated runtime constants discovered during live testing (VAD thresholds, silence padding, bucket rotation thresholds).

**`apps/web/`** — Next.js 16 (App Router), React 19, Tailwind CSS (Light Mode), managed with pnpm:

- `public/avatars/`: Self-hosted Meshopt-compressed Mixamo/ARKit .glb teacher model.
- `src/lib/api-client/`: Auto-generated TypeScript and Zod clients built solely from FastAPI's OpenAPI specification.
- `src/lib/audio/`: LiveKit audio element binding, unconditional silent zero-gain Web Audio tap, HeadAudio worklet bridge, and arm-gated RMS playout clock.
- `src/lib/whiteboard/`: MathJax 3 (tex2svg) compiler, function-plot SVG serializer, Excalidraw native element injector, and circle-to-ask bounding-box matcher.
- `src/components/classroom/`: Root persistent WebGL avatar stage, GPU FLIP layout controller, Excalidraw board workspace, slide switcher, manual layout pin toggle, and dev telemetry HUD.
- `src/components/courses/`: Light Mode course setup, PDF upload, syllabus tree inspector, and mastery dashboard.

**`apps/api/`** — Python 3.11+, FastAPI, LiveKit Agents Worker, Alembic, and psycopg3, managed with uv:

- `alembic/`: Single source of truth for all PostgreSQL schema and extension migrations.
- `schemas/`: Pydantic v2 models for REST payloads, LiveKit DataChannel messages, and internal FSM state snapshots.
- `db/`: Async psycopg3 connection pool and strictly typed repositories enforcing ltree chapter fencing.
- `ingestion/`: Math-aware PDF parser, Gemini Vision scanned-page fallback, curriculum tree extractor, formula-preserving chunker, and local fastembed embedding worker.
- `llm/`: Single-key Groq model-bucket router, response header quota tracker, circuit breaker, Gemini Flash / Ollama failover chain, cachetools LRU cache, and line-delimited stream parser.
- `tutor/`: 5-state explicit Python Pedagogical FSM, 4,000-token prompt budget assembler, scope guardrail policy, and CLI text simulation harness.
- `voice/`: LiveKit room token minter, LiveKit worker, Silero VAD pipeline, two-stage barge-in controller, Whisper STT client with hallucination guard, and server-side kokoro-onnx int8 synthesizer with sample-accurate PCM tracking.
- `board/`: 4-zone virtual 1280×720 spatial layout allocator, height estimator, and auto-pagination manager.
- `exports/`: Session event replayer queries and Markdown/PDF chapter cheat-sheet generator.

### AI-Agent Execution Rules (For .agents/PATTERNS.md)

Instruct your coding agent to enforce these hard rules on every pull request or session:

- **One Phase Per Session:** Never start Phase N+1 until every verification gate in Phase N passes and is recorded in .agents/ROADMAP.md.
- **Zero Direct Frontend Database Access:** Next.js never installs an ORM or connects to Supabase Postgres directly. All schema changes originate in apps/api Alembic migrations and Pydantic schemas, then propagate to apps/web via OpenAPI codegen.
- **Zero Banned Components:** Reject any introduction of Ready Player Me, browser-side HeadTTS, KaTeX-in-SVG injection, tldraw, Redis, LangGraph, Drizzle/Prisma, multi-key Groq rotation, retired Llama models (llama-3.1-8b-instant, llama-3.3-70b-versatile), or JSON tool calling for mid-lecture formulas.
- **Zero Heavy Blur Over WebGL/Canvas:** Keep Light Mode styling flat and crisp; forbid expensive backdrop-filter blur overlays across the avatar or Excalidraw surfaces.

## 2. Pre-Build Provisioning Checklist (Zero-Cost Accounts & Local Setup)

Complete these setup items before instructing the AI agent to execute Phase 1:

- **Supabase Free Tier:** Provision one project, record the pooled and direct PostgreSQL connection strings, and confirm vector and ltree extensions are available. Keep zero local Postgres Docker containers running.
- **Groq Cloud (Single Free API Key):** Confirm access to the three active free model buckets (openai/gpt-oss-20b, openai/gpt-oss-120b, qwen/qwen3.8-27b) and whisper-large-v3-turbo.
- **Google AI Studio (Free Tier, No Billing Card):** Generate an API key with access to gemini-3.8-flash (for syllabus extraction, scanned-page Vision recovery, and Tier-2 failover with free context caching) and gemini-3.5-flash-lite.
- **LiveKit:** Install the native livekit-server binary locally for unlimited zero-cost development testing, and create a LiveKit Cloud Build Free account (5,000 participant minutes and 1,000 agent minutes per month) for hosted deployment.
- **Local AI Weights (Pre-Downloaded Once):** Download the kokoro-onnx int8 weights and voice pack, Silero VAD ONNX model, and BAAI/bge-small-en-v1.5 weights for fastembed. Install Ollama locally only as a stopped service for offline emergency fallback.
- **Teacher 3D Avatar Asset:** Source or export one clean Mixamo-rigged teacher .glb model with ARKit and Oculus viseme blend shapes, compress it with Meshopt, and store it under apps/web/public/avatars/.

## 3. Master Ownership & Contract Matrix

Every invariant and interface maps to a single responsible subsystem so the coding agent never duplicates logic across frontend and backend:

| Contract Area | Canonical Owner | Exact Specification |
|---|---|---|
| Database Schema | apps/api/alembic | Five tables: courses, syllabus_nodes (GiST-indexed ltree path, mastery status, summaries at most 250 tokens), document_chunks (subtopic-fenced ltree path, intact raw LaTeX blocks, HNSW-indexed 384d embeddings), tutor_sessions (hard active_chapter_path, current_node_path, FSM state, monotonic active_turn_id, JSONB resume_stack, latest Excalidraw snapshot), and session_events (append-only timeline). |
| Pedagogical FSM | apps/api/tutor | Five explicit states: ONBOARDING, TEACH_STEP, MICRO_CHECK, INTERRUPT_QA, and RECAP. Persists state and resume_stack to tutor_sessions on every transition. |
| LLM Streaming Directives | apps/api/llm | Single-pass newline-delimited tokens: SAY: (natural spoken prose), LATEX: (raw unescaped math), PLOT: (function expression and domain), DIAGRAM: (structured diagram), CLEAR: (slide or layout switch), and CTRL: (state transition such as advancing subtopic). |
| Server-to-Client DataChannel | apps/api/schemas | Six ordered event types: AUDIO_SEGMENT_START (turn_id, segment_id as "filler" or "response"), BOARD_SCHEDULE (turn_id, layout_mode, allocated BoardOp list with playout_offset_ms), PLAYOUT_PAUSE, PLAYOUT_RESUME (rewind_ms, default 200ms), INTERRUPT_FLUSH (new_turn_id), and AVATAR_CUE (listening, thinking, speaking, idle). |
| Client-to-Server DataChannel | apps/web/src/lib | Two event types: BOARD_SELECTION (referenced_op_id, label, raw LaTeX or expression payload) and LAYOUT_OVERRIDE (FULL_AVATAR, PIP_WHITEBOARD, or AUTO). |
| Audio & Playout Clock | apps/api/voice + apps/web/src/lib/audio | Server prepends 150ms digital silence before each turn, counts exact 24kHz PCM samples for playout_offset_ms, and streams exclusively over a LiveKit remote AudioTrack. Client plays audible sound strictly through a standard HTML audio element (autoplay, playsInline) for hardware AEC, while tapping the remote MediaStream into HeadAudio and RMS detection through an unconditional zero-gain node into the audio context destination. |
| Spatial Whiteboard | apps/api/board + apps/web/src/lib/whiteboard | Server owns a 1280×720 virtual grid with four non-overlapping zones (header, derivation, visual, callout) and emits CLEAR_SLIDE on vertical overflow. Client compiles math via MathJax 3 tex2svg with font caching disabled and plots via function-plot into pure vector SVGs injected natively as Excalidraw image elements with semantic customData. |
| Avatar Transitions | apps/web/src/components/classroom | Single persistent 30fps WebGL canvas mounted at classroom root. Transitions between Full Avatar and 200×200px top-right PiP animate only GPU-composited transform (translate3d and scale) and clip-path over ~280ms; Three.js resize and camera reframe run once on transitionend. |

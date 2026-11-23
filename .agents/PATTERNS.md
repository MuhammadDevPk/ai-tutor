# AI Tutor — Patterns & Guardrails (harness)

> Extracted verbatim from IMPLEMENTATION-PLAN.md, Sections 1-3, per Phase 1 of the plan.
> The Anti-Drift Guardrails (Do-Not-Build list) in Section 1 and the Seven Invariants in Section 2 are mandatory for every change.

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

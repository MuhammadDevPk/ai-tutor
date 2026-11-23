# PATTERNS.md — Non-Negotiable Invariants & Do-Not-Build Rules

## Do-Not-Build List (Mechanically Enforced in scripts/verify.sh)
- NO Ready Player Me URLs or SDKs (self-hosted Meshopt `.glb` in `apps/web/public/avatars/` only).
- NO browser-side TTS / HeadTTS (breaks WebRTC hardware AEC over laptop speakers).
- NO KaTeX for whiteboard SVG injection (use `mathjax-full` `tex2svg` with `fontCache: "none"`).
- NO `tldraw` (MIT Excalidraw with native SVG image elements only).
- NO Redis, NO LangGraph, NO Drizzle/Prisma/frontend Postgres drivers.
- NO JSON tool calling for mid-lecture formulas (use single-pass line-delimited directives).
- NO multi-key Groq farming and NO retired Llama models (`llama-3.1-8b-instant`, `llama-3.3-70b-versatile`).
- NO heavy `backdrop-filter` blur over WebGL or Excalidraw canvases.

## Seven System Invariants
1. **Single-Path AEC Audio Graph:** Server `kokoro-onnx` (24kHz mono PCM) -> LiveKit remote AudioTrack -> browser `<audio autoplay playsInline>` (audible output). Lip-sync (HeadAudio) and RMS onset tap the remote `MediaStream` via `MediaStreamAudioSourceNode -> Worklet -> GainNode(0) -> audioCtx.destination` unconditionally in Chromium and Safari.
2. **Sample-Accurate Playout Clock:** Server prepends 150ms digital silence per turn, computes `playout_offset_ms` from exact Kokoro PCM sample counts, and emits `AUDIO_SEGMENT_START` (`"filler"` or `"response"`). Client arms RMS onset strictly on `"response"`, never on `"filler"`.
3. **Two-Stage Backchannel-Safe Barge-In:** Stage 1 (soft duck at >200ms speech) emits `PLAYOUT_PAUSE` without canceling LLM/board ops. Whisper STT + Backchannel/Hallucination Guard decides: backchannel/noise -> rewind Kokoro PCM 200ms + `PLAYOUT_RESUME(rewind_ms)`; real question -> increment `turn_id`, cancel tasks, `INTERRUPT_FLUSH`, push unplayed items to `resume_stack`.
4. **Line-Delimited Stream Protocol:** LLM streams `SAY:`, `LATEX:`, `PLOT:`, `DIAGRAM:`, `CLEAR:`, `CTRL:`. Never JSON-decode `LATEX:` lines (preserves `\bar`, `\frac`, `\text`, `\nu`, `\rho` verbatim). Run math-to-speech regex sanitizer on `SAY:`.
5. **GPU-Composited FLIP Avatar:** One permanently mounted 30fps WebGL canvas. Full <-> 200x200px PiP animates ONLY `transform` (`translate3d`, `scale`) and `clip-path`; call Three.js `setSize()` and camera reframe ONCE on `transitionend`.
6. **Database-Enforced Curriculum Fencing:** Every RAG query applies PostgreSQL `syllabus_path <@ active_chapter_path`. Sanitize extracted PDF headings into valid `ltree` labels (`[A-Za-z0-9_]+`) before insert.
7. **4,000-Token Cap & Latency Masking:** Static cached system prefix (~750 tokens) + subtopic brief (~500) + top-3 chunks (~900) + semantic board summary (~300, never raw Excalidraw JSON) + rolling memory (~1,000) + completion (~550). Emit `AVATAR_CUE: thinking` immediately at VAD end; play cached `"filler"` if TTS exceeds 1,100ms.

## Hard Implementation Edge Cases
- **Late DataChannel packets:** If a `BoardOp` arrives after its `playout_offset_ms` has passed for the current active `turn_id`, render it immediately rather than dropping it.
- **Compact DB snapshots:** Persist canonical `BoardOp` arrays in `tutor_sessions` and recompile SVGs on reload; never store bloated base64 SVG blobs in Postgres JSONB.
- **Idempotent PDF ingestion:** Re-uploading or retrying a document cleanly replaces partial `syllabus_nodes` and `document_chunks` for that source document.

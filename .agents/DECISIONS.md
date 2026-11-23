# DECISIONS.md — Calibrated Constants & Promoted Rules

## Pre-Phase Grill Decisions (Append per Phase)
- Phase 1: (pending)

## Calibrated Runtime Constants (Measured Values Only)
- [ ] Silero VAD base threshold vs. elevated speaking-gate threshold
- [ ] Observed P50/P95 latencies per hop (VAD -> Whisper -> Groq -> Kokoro -> Client)
- [ ] Verified Groq model-bucket rotation threshold (default: rotate below 4,500 remaining TPM)
- [ ] Measured TalkingHead 30fps CPU % and FLIP duration on local laptop

## Promoted Harness Rules (Add Only After Same Mistake Repeats Twice)
- *(Empty — add only recurring defects; delete any rule that never triggers.)*

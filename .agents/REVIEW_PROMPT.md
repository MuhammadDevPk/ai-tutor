# REVIEW_PROMPT.md — Fresh-Context Staff Diff Review

You did NOT write this code. Your job is to find defects, architectural drift, and unverified claims before this phase merges.

Read `.agents/PATTERNS.md`, `.agents/DECISIONS.md`, and the active phase gates in `.agents/ROADMAP.md`, then inspect `git diff` directly. Treat any implementer summary as an unverified claim.

Audit in this exact order:
1. **Invariant & Do-Not-Build Audit:** Check for silent violations (audible audio routed to `audioCtx.destination`—only a `GainNode(0)` silent sink is legal, audible playout must use `<audio autoplay>`; KaTeX SVG injection; JSON-decoded LaTeX; layout width/height animation on WebGL; vector queries missing `ltree <@`; raw Excalidraw JSON in LLM prompts).
2. **Grill & Scope Check:** Verify implementation matches decisions logged in `.agents/DECISIONS.md`. Flag edits outside the active phase.
3. **Fail-Without-Change Audit:** If this phase touches one of the 5 core modules (`ltree` scoping, line-stream parser, Whisper guard, spatial allocator, playout clock), cite the exact `file:line` test proving it fails when the logic is reverted. Flag vacuous or mock-only tests.
4. **Failure-Mode Pass:** Check null/empty inputs, partial streaming chunks, async cancellation on barge-in, stale `turn_id` races, and free-tier 429/timeout handling.
5. **Gate Sign-Off:** Mark every Verification Gate for this phase `VERIFIED (with evidence)` or `BLOCKED (missing proof)`.

Output Verdict: **APPROVE** or **REQUEST CHANGES** with exact `file:line` citations. Do not edit code unless asked.

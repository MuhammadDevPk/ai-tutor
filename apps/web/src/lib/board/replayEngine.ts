/**
 * Pure event-sourcing replay engine for ai-tutor.
 *
 * Reconstructs exact board state (active slide ops + archived slide strip),
 * FSM cursor, speech transcripts, and INTERRUPT_QA context at any point
 * along the session timeline.
 */

import type { BoardOp, SessionEvent } from "@/lib/api-client";

export interface ReplaySlide {
  slideNumber: number;
  ops: BoardOp[];
}

export interface ReplayState {
  currentStep: number;
  totalSteps: number;
  currentTurnId: number;
  currentFsmState: string;
  currentSubtopic: string;
  activeSlideIndex: number;
  activeSlideOps: BoardOp[];
  archivedSlides: ReplaySlide[];
  teacherSayText: string | null;
  studentSpeechText: string | null;
  isInterruptLoop: boolean;
  activeMisconception: {
    question: string;
    clarification: string;
    subtopic: string;
  } | null;
  allFormulas: Array<{ latex: string; label: string; opId: string }>;
}

export function computeReplayStateAtStep(
  events: SessionEvent[],
  stepIndex: number
): ReplayState {
  const boundedStep = Math.max(0, Math.min(stepIndex, events.length));
  const slice = events.slice(0, boundedStep);

  let currentTurnId = 0;
  let currentFsmState = "ONBOARDING";
  let currentSubtopic = "";
  let teacherSayText: string | null = null;
  let studentSpeechText: string | null = null;
  let isInterruptLoop = false;
  let activeMisconception: {
    question: string;
    clarification: string;
    subtopic: string;
  } | null = null;

  const activeSlideOps: BoardOp[] = [];
  const archivedSlides: ReplaySlide[] = [];
  const allFormulas: Array<{ latex: string; label: string; opId: string }> = [];

  for (let i = 0; i < slice.length; i++) {
    const ev = slice[i];
    currentTurnId = ev.turn_id ?? currentTurnId;
    const evType = ev.event_type || "";
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const payload = (ev.payload || {}) as Record<string, any>;

    if (evType === "STATE_CHANGE") {
      const toState = String(payload.to_state || "");
      currentFsmState = toState || currentFsmState;
      currentSubtopic = String(payload.current_node_path || currentSubtopic);
      isInterruptLoop = toState === "INTERRUPT_QA";
    } else if (evType === "STUDENT_MESSAGE") {
      studentSpeechText = String(payload.text || "");
    } else if (evType === "SayEvent" || evType === "SAY") {
      teacherSayText = String(payload.text || "");
    } else if (evType === "ClearEvent" || (evType === "BOARD_OP" && payload.op_type === "clear")) {
      if (activeSlideOps.length > 0) {
        archivedSlides.push({
          slideNumber: archivedSlides.length + 1,
          ops: [...activeSlideOps],
        });
        activeSlideOps.length = 0;
      }
    } else if (
      evType === "LatexEvent" ||
      evType === "PlotEvent" ||
      evType === "DiagramEvent" ||
      evType === "BOARD_OP"
    ) {
      const opType =
        evType === "LatexEvent"
          ? "latex"
          : evType === "PlotEvent"
          ? "plot"
          : evType === "DiagramEvent"
          ? "diagram"
          : String(payload.op_type || "latex");

      const opId = String(payload.op_id || `op_${ev.turn_id}_${activeSlideOps.length + 1}`);
      const rawPayload = payload.payload && typeof payload.payload === "object" ? payload.payload : payload;
      const latex = String(rawPayload.latex || rawPayload.raw || payload.latex || "");
      const label = String(rawPayload.label || payload.label || `Formula ${activeSlideOps.length + 1}`);

      const boardOp: BoardOp = {
        op_id: opId,
        op_type: opType,
        playout_offset_ms: ev.playout_offset_ms || 0,
        payload: {
          ...rawPayload,
          latex,
          raw: latex,
          label,
        },
      };

      activeSlideOps.push(boardOp);

      if (opType === "latex" && latex) {
        if (!allFormulas.some((f) => f.latex === latex)) {
          allFormulas.push({ latex, label, opId });
        }
      }
    } else if (evType === "MISCONCEPTION_CLEARED") {
      activeMisconception = {
        question: String(payload.question || ""),
        clarification: String(payload.clarification || ""),
        subtopic: String(payload.subpoint_name || payload.subtopic_path || ""),
      };
      isInterruptLoop = false;
    }
  }

  return {
    currentStep: boundedStep,
    totalSteps: events.length,
    currentTurnId,
    currentFsmState,
    currentSubtopic,
    activeSlideIndex: archivedSlides.length,
    activeSlideOps,
    archivedSlides,
    teacherSayText,
    studentSpeechText,
    isInterruptLoop,
    activeMisconception,
    allFormulas,
  };
}

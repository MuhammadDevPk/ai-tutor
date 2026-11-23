/**
 * expressionMapper.ts — Translates AVATAR_CUE events into TalkingHead mood & pose parameters.
 *
 * Rules: Subtle, academic, realistic micro-motions (never cartoonish).
 * Cues:
 * - listening: direct eye contact, slight inquisitive head tilt, attentive brow
 * - thinking: gaze deflected aside/upward, subtle reflective head tilt, neutral mood
 * - speaking: eye contact, breathing, gentle rhythmic nodding micro-motions
 * - idle: relaxed neutral baseline, breathing, soft blink-friendly gaze
 */

export type AvatarCue = "listening" | "thinking" | "speaking" | "idle";

export interface AvatarExpression {
  cue: AvatarCue;
  mood: string;
  eyeContact: boolean;
  /** Camera gaze direction in normalised units [-1, 1] */
  gaze: { x: number; y: number };
  /** Head tilt / rotation targets in radians */
  headRotation: { x: number; y: number; z: number };
  /** TalkingHead morph target / blend shape system overrides */
  morphTargets: Record<string, number>;
  /** Suggested transition time in milliseconds */
  transitionMs: number;
}

export const CUE_EXPRESSIONS: Record<AvatarCue, AvatarExpression> = {
  listening: {
    cue: "listening",
    mood: "neutral",
    eyeContact: true,
    gaze: { x: 0.0, y: 0.0 }, // Direct eye contact with student
    headRotation: { x: 0.02, y: 0.0, z: 0.04 }, // Slight inquisitive forward tilt
    morphTargets: {
      browInnerUp: 0.12, // Attentive brow
      eyeWideLeft: 0.05,
      eyeWideRight: 0.05,
    },
    transitionMs: 400,
  },
  thinking: {
    cue: "thinking",
    mood: "neutral",
    eyeContact: false,
    gaze: { x: 0.25, y: 0.2 }, // Gaze aside and slightly upward
    headRotation: { x: 0.06, y: -0.08, z: -0.05 }, // Subtle reflective tilt
    morphTargets: {
      browInnerUp: 0.08,
      eyesRotateY: 0.15,
      eyesRotateX: 0.1,
    },
    transitionMs: 500,
  },
  speaking: {
    cue: "speaking",
    mood: "neutral",
    eyeContact: true,
    gaze: { x: 0.0, y: 0.0 }, // Eye contact while explaining
    headRotation: { x: 0.04, y: 0.0, z: 0.0 }, // Slight forward engagement
    morphTargets: {
      mouthSmile: 0.08, // Subtle pleasant warmth
    },
    transitionMs: 300,
  },
  idle: {
    cue: "idle",
    mood: "neutral",
    eyeContact: true,
    gaze: { x: 0.0, y: 0.0 }, // Relaxed neutral
    headRotation: { x: 0.0, y: 0.0, z: 0.0 }, // Upright posture
    morphTargets: {
      eyesLookDown: 0.04, // Soft, natural relaxed resting gaze
    },
    transitionMs: 600,
  },
};

/**
 * Pure function: maps an AVATAR_CUE string to an AvatarExpression specification.
 */
export function mapAvatarCueToExpression(cue: string | null | undefined): AvatarExpression {
  if (cue === "listening" || cue === "thinking" || cue === "speaking" || cue === "idle") {
    return CUE_EXPRESSIONS[cue];
  }
  return CUE_EXPRESSIONS.idle;
}

/**
 * Applies an AvatarExpression to a TalkingHead instance defensively.
 * Checks for method existence so tests and mock instances never fail.
 */
export function applyAvatarExpression(
  head: {
    setMood?: (mood: string) => void;
    setValue?: (mt: string, val: number, ms?: number | null) => void;
    lookAtCamera?: (ms?: number) => void;
  } | null | undefined,
  expression: AvatarExpression
): void {
  if (!head) return;

  try {
    if (typeof head.setMood === "function" && expression.mood) {
      head.setMood(expression.mood);
    }

    if (expression.eyeContact && typeof head.lookAtCamera === "function") {
      head.lookAtCamera(expression.transitionMs);
    }

    if (typeof head.setValue === "function") {
      // Apply head rotation
      head.setValue("bodyRotateX", expression.headRotation.x, expression.transitionMs);
      head.setValue("bodyRotateY", expression.headRotation.y, expression.transitionMs);
      head.setValue("bodyRotateZ", expression.headRotation.z, expression.transitionMs);

      // Apply morph targets
      for (const [mt, val] of Object.entries(expression.morphTargets)) {
        head.setValue(mt, val, expression.transitionMs);
      }
    }
  } catch (err) {
    console.warn("applyAvatarExpression: failed to apply expression to head", err);
  }
}

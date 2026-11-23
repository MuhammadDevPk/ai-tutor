/**
 * silentTap.ts — Unconditional zero-gain Web Audio tap on the remote
 * MediaStream.
 *
 * Purpose: keep the AudioContext processing pipeline alive (Chromium
 * and Safari suspend AudioContext.destination if nothing is connected)
 * and feed RMS samples to the playout clock onset detector.
 *
 * INVARIANT: Audible playback stays STRICTLY on the Phase 5 HTML
 * <audio> element. The tap's gain is ALWAYS 0.  This preserves the
 * single-path AEC audio graph.
 */

export const ANALYSER_FFT_SIZE = 2048;

export interface SilentTapHandle {
  /** The AudioContext used by the tap. */
  ctx: AudioContext;
  /** The AnalyserNode for RMS computation. */
  analyser: AnalyserNode;
  /** Call to compute current RMS from the analyser time-domain data. */
  getRms: () => number;
  /** Disconnect and close the tap. */
  dispose: () => void;
}

/**
 * Create a silent zero-gain tap on a remote MediaStream.
 *
 * Graph:
 *   MediaStreamAudioSourceNode -> AnalyserNode -> GainNode(0) -> destination
 *
 * The GainNode is locked to 0 so no audible output ever passes through.
 */
export function createSilentTap(stream: MediaStream): SilentTapHandle {
  const ctx = new AudioContext({ sampleRate: 24000 });
  const source = ctx.createMediaStreamSource(stream);

  const analyser = ctx.createAnalyser();
  analyser.fftSize = ANALYSER_FFT_SIZE;

  const gain = ctx.createGain();
  gain.gain.value = 0; // ZERO — never audible

  source.connect(analyser);
  analyser.connect(gain);
  gain.connect(ctx.destination);

  if (ctx.state === "suspended") {
    void ctx.resume();
  }

  const timeDomainBuffer = new Float32Array(analyser.fftSize);

  function getRms(): number {
    if (ctx.state === "suspended") {
      void ctx.resume();
    }
    analyser.getFloatTimeDomainData(timeDomainBuffer);
    let sum = 0;
    for (let i = 0; i < timeDomainBuffer.length; i++) {
      sum += timeDomainBuffer[i] * timeDomainBuffer[i];
    }
    return Math.sqrt(sum / timeDomainBuffer.length);
  }

  function dispose(): void {
    try {
      source.disconnect();
      analyser.disconnect();
      gain.disconnect();
    } catch {
      // already disconnected
    }
    void ctx.close();
  }

  return { ctx, analyser, getRms, dispose };
}

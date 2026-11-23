/**
 * headAudioBridge.ts — AudioWorklet bridge tapping the Phase 7 silent tap read-only.
 *
 * System Invariant 1:
 * Server kokoro-onnx (24kHz mono PCM) -> LiveKit remote AudioTrack -> browser <audio autoplay playsInline>.
 * Lip-sync (HeadAudio) taps the remote MediaStream via
 * MediaStreamAudioSourceNode -> Worklet -> GainNode(0) -> audioCtx.destination.
 *
 * Audible playback remains strictly on the HTML audio element.
 * The worklet NEVER creates an audible path.
 */

export interface VisemeMessage {
  type: "viseme";
  viseme: string;
  weight: number;
  energy: number;
  isVoice: boolean;
}

export type VisemeCallback = (msg: VisemeMessage) => void;

export interface HeadAudioBridgeHandle {
  dispose: () => void;
}

/**
 * AudioWorkletProcessor script source executed in the Web Audio rendering thread.
 * Computes real-time RMS energy and zero-crossing rate from the 24kHz PCM stream,
 * producing phonetic viseme weights at ~50Hz.
 */
const HEAD_AUDIO_WORKLET_CODE = `
class HeadAudioWorkletProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._blockCounter = 0;
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (!input || !input[0] || input[0].length === 0) {
      return true;
    }

    const samples = input[0];
    const len = samples.length;

    // Calculate energy (RMS) and zero crossing rate
    let sum = 0;
    let signChanges = 0;
    for (let i = 0; i < len; i++) {
      const s = samples[i];
      sum += s * s;
      if (i > 0 && ((samples[i] >= 0 && samples[i - 1] < 0) || (samples[i] < 0 && samples[i - 1] >= 0))) {
        signChanges++;
      }
    }
    const rms = Math.sqrt(sum / len);
    const zcr = signChanges / len;

    // Throttle message rate: 4 blocks of 128 samples = 512 samples (~21.3ms at 24kHz)
    this._blockCounter++;
    if (this._blockCounter >= 4) {
      this._blockCounter = 0;

      // Voice activity threshold
      const isVoice = rms > 0.012;
      let viseme = "sil";
      let weight = 0;

      if (isVoice) {
        weight = Math.min(1.0, Math.max(0.2, (rms - 0.01) * 7.5));
        if (zcr > 0.35) {
          viseme = "SS";
        } else if (zcr > 0.20) {
          viseme = "E";
        } else if (zcr > 0.10) {
          viseme = "aa";
        } else {
          viseme = "O";
        }
      }

      this.port.postMessage({
        type: "viseme",
        viseme,
        weight,
        energy: rms,
        isVoice
      });
    }

    // Keep outputs silent (zero-gain guaranteed)
    if (outputs[0] && outputs[0][0]) {
      outputs[0][0].fill(0);
    }
    return true;
  }
}

registerProcessor("headaudio-processor", HeadAudioWorkletProcessor);
`;

/**
 * Creates and connects the HeadAudio worklet to an existing silent tap AudioContext.
 *
 * Graph:
 *   MediaStreamSource -> AudioWorkletNode -> GainNode(0) -> AudioContext.destination
 *
 * Audible output: 0.0 (strictly silent).
 */
export async function createHeadAudioBridge(
  ctx: AudioContext,
  stream: MediaStream,
  onViseme: VisemeCallback
): Promise<HeadAudioBridgeHandle> {
  const blob = new Blob([HEAD_AUDIO_WORKLET_CODE], {
    type: "application/javascript",
  });
  const workletUrl = URL.createObjectURL(blob);

  let disposed = false;
  let sourceNode: MediaStreamAudioSourceNode | null = null;
  let workletNode: AudioWorkletNode | null = null;
  let silentGainNode: GainNode | null = null;

  try {
    await ctx.audioWorklet.addModule(workletUrl);
    if (disposed) {
      URL.revokeObjectURL(workletUrl);
      return { dispose: () => {} };
    }

    sourceNode = ctx.createMediaStreamSource(stream);
    workletNode = new AudioWorkletNode(ctx, "headaudio-processor");

    // Zero-gain node to prevent any audible sound while keeping destination pipeline active
    silentGainNode = ctx.createGain();
    silentGainNode.gain.value = 0;

    sourceNode.connect(workletNode);
    workletNode.connect(silentGainNode);
    silentGainNode.connect(ctx.destination);

    workletNode.port.onmessage = (event: MessageEvent<VisemeMessage>) => {
      if (disposed) return;
      if (event.data && event.data.type === "viseme") {
        onViseme(event.data);
      }
    };
  } catch (err) {
    console.warn("createHeadAudioBridge: failed to initialize AudioWorklet", err);
  } finally {
    URL.revokeObjectURL(workletUrl);
  }

  return {
    dispose: () => {
      disposed = true;
      try {
        if (workletNode) {
          workletNode.port.onmessage = null;
          workletNode.disconnect();
        }
        if (sourceNode) {
          sourceNode.disconnect();
        }
        if (silentGainNode) {
          silentGainNode.disconnect();
        }
      } catch {
        // already disconnected
      }
    },
  };
}

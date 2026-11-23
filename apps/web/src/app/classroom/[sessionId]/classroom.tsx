"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  ConnectionState,
  RemoteAudioTrack,
  Room,
  RoomEvent,
  Track,
} from "livekit-client";
import type {
  LiveKitTokenResponse,
  BoardScheduleEvent,
  BoardSelectionEvent,
  AudioSegmentStartEvent,
  PlayoutResumeEvent,
  InterruptFlushEvent,
  LayoutOverrideEvent,
} from "@/lib/api-client";
import BoardWorkspace, {
  type BoardOpWithPlacement,
} from "@/components/classroom/BoardWorkspace";
import TelemetryHud, {
  type TelemetryData,
} from "@/components/classroom/TelemetryHud";
import AvatarStage, {
  type AvatarStageHandle,
} from "@/components/classroom/AvatarStage";
import LayoutPinControl from "@/components/classroom/LayoutPinControl";
import { PlayoutClock } from "@/lib/board/playoutClock";
import { createSilentTap, type SilentTapHandle } from "@/lib/audio/silentTap";
import {
  type LayoutMode,
  type EffectiveLayout,
  resolveEffectiveLayout,
  createHeadAudioBridge,
  type HeadAudioBridgeHandle,
} from "@/lib/avatar";

export default function ClassroomAudioShell({
  sessionId,
}: {
  sessionId: string;
}) {
  const router = useRouter();
  const [connectionState, setConnectionState] = useState<ConnectionState>(
    ConnectionState.Disconnected
  );
  const [isMuted, setIsMuted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Board operations received over LiveKit DataChannel
  const [boardOperations, setBoardOperations] = useState<BoardOpWithPlacement[]>([]);

  // Phase 8: Layout mode, Avatar Cue, and speaking state
  const [layoutMode, setLayoutMode] = useState<LayoutMode>("AUTO");
  const [avatarCue, setAvatarCue] = useState<string>("idle");
  const [isSpeaking, setIsSpeaking] = useState<boolean>(false);

  // Telemetry HUD data
  const [telemetryData, setTelemetryData] = useState<TelemetryData>({
    turnId: 0,
    elapsedMs: 0,
    vadState: "idle",
    activeLlmBucket: "n/a",
    groqTpmRemaining: null,
    latencies: {},
  });

  // HARD INVARIANT: Standard HTML audio element only.
  // Never pass this element into Web Audio API AudioContext / createMediaElementSource.
  const audioElementRef = useRef<HTMLAudioElement | null>(null);
  const roomRef = useRef<Room | null>(null);
  const silentTapRef = useRef<SilentTapHandle | null>(null);
  const headAudioRef = useRef<HeadAudioBridgeHandle | null>(null);
  const avatarStageRef = useRef<AvatarStageHandle | null>(null);
  const playoutClockRef = useRef<PlayoutClock | null>(null);
  const rafIdRef = useRef<number | null>(null);

  const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  // Resolve effective layout (Full Avatar vs PiP Whiteboard)
  const effectiveLayout: EffectiveLayout = resolveEffectiveLayout(
    layoutMode,
    isSpeaking,
    boardOperations.length > 0
  );

  // Handle manual layout mode override
  const handleLayoutChange = useCallback((newMode: LayoutMode) => {
    setLayoutMode(newMode);
    const room = roomRef.current;
    if (room && room.state === ConnectionState.Connected) {
      try {
        const overrideEvent: LayoutOverrideEvent = {
          event_type: "LAYOUT_OVERRIDE",
          mode: newMode,
        };
        const bytes = new TextEncoder().encode(JSON.stringify(overrideEvent));
        room.localParticipant.publishData(bytes, { reliable: true });
      } catch (err) {
        console.warn("Failed to publish LAYOUT_OVERRIDE over DataChannel:", err);
      }
    }
  }, []);

  // Initialize playout clock
  useEffect(() => {
    const clock = new PlayoutClock({
      clock: () => performance.now(),
      onRelease: (op) => {
        // Released ops go to BoardWorkspace injector
        setBoardOperations((prev) => [...prev, op as BoardOpWithPlacement]);
      },
    });
    playoutClockRef.current = clock;

    // requestAnimationFrame tick loop
    const tick = () => {
      clock.tick();
      setTelemetryData((prev) => ({
        ...prev,
        turnId: clock.activeTurnId,
        elapsedMs: clock.elapsedMs,
      }));
      rafIdRef.current = requestAnimationFrame(tick);
    };
    rafIdRef.current = requestAnimationFrame(tick);

    return () => {
      if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current);
      }
      clock.reset();
    };
  }, []);

  // Circle-to-Ask: publish BOARD_SELECTION event over DataChannel
  const handleBoardSelection = useCallback(async (event: BoardSelectionEvent) => {
    const room = roomRef.current;
    if (!room || room.state !== ConnectionState.Connected) return;

    try {
      const payloadBytes = new TextEncoder().encode(JSON.stringify(event));
      await room.localParticipant.publishData(payloadBytes, {
        reliable: true,
      });
    } catch (err) {
      console.warn("Failed to publish BOARD_SELECTION over DataChannel:", err);
    }
  }, []);

  // Handle DataChannel events with playout clock integration
  const handleDataChannelEvent = useCallback((parsed: Record<string, unknown>) => {
    const clock = playoutClockRef.current;
    if (!clock) return;

    switch (parsed.event_type) {
      case "BOARD_SCHEDULE": {
        const scheduleEvent = parsed as unknown as BoardScheduleEvent;
        if (scheduleEvent.operations && scheduleEvent.operations.length > 0) {
          for (const op of scheduleEvent.operations) {
            clock.enqueue(scheduleEvent.turn_id, op);
          }
        }
        break;
      }
      case "AUDIO_SEGMENT_START": {
        const segEvent = parsed as unknown as AudioSegmentStartEvent;
        clock.onSegmentStart(
          segEvent.turn_id,
          segEvent.segment_id as "filler" | "response"
        );
        break;
      }
      case "PLAYOUT_PAUSE": {
        clock.onPlayoutPause();
        break;
      }
      case "PLAYOUT_RESUME": {
        const resumeEvent = parsed as unknown as PlayoutResumeEvent;
        clock.onPlayoutResume(resumeEvent.rewind_ms);
        break;
      }
      case "INTERRUPT_FLUSH": {
        const flushEvent = parsed as unknown as InterruptFlushEvent;
        const lastRenderedOpId = clock.onInterruptFlush(flushEvent.new_turn_id);
        // Report last rendered op_id back over DataChannel
        const room = roomRef.current;
        if (room && room.state === ConnectionState.Connected && lastRenderedOpId) {
          const report = {
            event_type: "BOARD_SELECTION",
            referenced_op_id: lastRenderedOpId,
            label: "__interrupt_ack__",
            payload: "",
          };
          const bytes = new TextEncoder().encode(JSON.stringify(report));
          room.localParticipant.publishData(bytes, { reliable: true }).catch(() => {
            // best-effort
          });
        }
        // Clear board ops for the old turn
        setBoardOperations([]);
        break;
      }
      case "AVATAR_CUE": {
        const cue = parsed as { cue?: string };
        const cueVal = cue.cue || "idle";
        setAvatarCue(cueVal);
        setIsSpeaking(cueVal === "speaking");
        avatarStageRef.current?.applyCue(cueVal);
        setTelemetryData((prev) => ({
          ...prev,
          vadState: cueVal,
        }));
        break;
      }
      default:
        break;
    }
  }, []);

  useEffect(() => {
    let active = true;
    const room = new Room({
      adaptiveStream: true,
      dynacast: true,
    });
    roomRef.current = room;

    const connectToRoom = async () => {
      try {
        const authToken = localStorage.getItem("auth_token") || "";
        const headers: Record<string, string> = authToken
          ? { Authorization: `Bearer ${authToken}` }
          : {};

        // Fetch LiveKit Room JWT
        const res = await fetch(`${apiBase}/sessions/${sessionId}/livekit-token`, {
          method: "POST",
          headers,
        });

        if (!active) return;
        if (!res.ok) {
          if (res.status === 401) {
            throw new Error("Unauthorized. Please log in first.");
          }
          if (res.status === 404) {
            throw new Error("Tutor session not found or access denied.");
          }
          throw new Error(`Failed to mint LiveKit token: HTTP ${res.status}`);
        }

        const data: LiveKitTokenResponse = await res.json();
        const serverUrl = data.url || process.env.NEXT_PUBLIC_LIVEKIT_URL || "ws://localhost:7880";

        // Listen for connection changes
        room.on(RoomEvent.ConnectionStateChanged, (state) => {
          if (active) setConnectionState(state);
        });

        // Remote teacher audio track attachment
        room.on(RoomEvent.TrackSubscribed, (track: Track) => {
          if (track.kind === Track.Kind.Audio && track instanceof RemoteAudioTrack) {
            if (audioElementRef.current) {
              track.attach(audioElementRef.current);
            }

            // Phase 7: Create silent zero-gain Web Audio tap on the remote
            // MediaStream for RMS onset detection.  Audible playback stays
            // strictly on the HTML audio element (AEC invariant).
            const mediaStream = new MediaStream([
              track.mediaStreamTrack,
            ]);
            const tap = createSilentTap(mediaStream);
            silentTapRef.current = tap;

            // Feed RMS to the playout clock onset detector
            const rmsInterval = setInterval(() => {
              if (tap && playoutClockRef.current) {
                const rms = tap.getRms();
                playoutClockRef.current.onRmsSample(rms);
              }
            }, 20); // 20ms polling

            // Phase 8: Connect HeadAudio worklet bridge (Read-Only)
            let bridgeActive = true;
            createHeadAudioBridge(tap.ctx, mediaStream, (msg) => {
              const head = avatarStageRef.current?.getHead();
              if (!head) return;
              if (msg.isVoice && msg.weight > 0) {
                head.setValue("viseme_" + msg.viseme, msg.weight, 40);
                head.setValue("jawOpen", msg.weight * 0.7, 40);
              } else {
                head.setValue("viseme_aa", 0, 80);
                head.setValue("viseme_E", 0, 80);
                head.setValue("viseme_O", 0, 80);
                head.setValue("viseme_SS", 0, 80);
                head.setValue("jawOpen", 0, 80);
              }
            }).then((handle) => {
              if (active && bridgeActive) {
                headAudioRef.current = handle;
              } else {
                handle.dispose();
              }
            });

            // Store cleanup ref
            const prevDispose = tap.dispose;
            tap.dispose = () => {
              bridgeActive = false;
              clearInterval(rmsInterval);
              if (headAudioRef.current) {
                headAudioRef.current.dispose();
                headAudioRef.current = null;
              }
              prevDispose();
            };
          }
        });

        room.on(RoomEvent.TrackUnsubscribed, (track: Track) => {
          if (track.kind === Track.Kind.Audio) {
            if (audioElementRef.current) {
              track.detach(audioElementRef.current);
            }
            if (headAudioRef.current) {
              headAudioRef.current.dispose();
              headAudioRef.current = null;
            }
            // Clean up silent tap
            if (silentTapRef.current) {
              silentTapRef.current.dispose();
              silentTapRef.current = null;
            }
          }
        });

        // Listen for Server-to-Client DataChannel events
        room.on(RoomEvent.DataReceived, (payload: Uint8Array) => {
          if (!active) return;
          try {
            const rawText = new TextDecoder().decode(payload);
            const parsed = JSON.parse(rawText);
            handleDataChannelEvent(parsed);
          } catch {
            // Ignore non-JSON DataChannel packets defensively
          }
        });

        // Connect to room
        await room.connect(serverUrl, data.token);

        if (!active) return;

        // Publish student microphone with AEC, noise suppression, AGC
        await room.localParticipant.setMicrophoneEnabled(true, {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        });

        if (active) {
          setIsMuted(false);
          setError(null);
        }
      } catch (err: unknown) {
        if (active) {
          setError(err instanceof Error ? err.message : "Failed to connect to room");
        }
      }
    };

    const currentAudio = audioElementRef.current;

    connectToRoom();

    return () => {
      active = false;
      if (currentAudio) {
        currentAudio.srcObject = null;
      }
      if (headAudioRef.current) {
        headAudioRef.current.dispose();
        headAudioRef.current = null;
      }
      if (silentTapRef.current) {
        silentTapRef.current.dispose();
        silentTapRef.current = null;
      }
      room.disconnect();
      roomRef.current = null;
    };
  }, [sessionId, apiBase, handleDataChannelEvent]);

  const toggleMute = async () => {
    const room = roomRef.current;
    if (!room) return;
    const newMutedState = !isMuted;
    await room.localParticipant.setMicrophoneEnabled(!newMutedState);
    setIsMuted(newMutedState);
  };

  const handleEndSession = () => {
    if (roomRef.current) {
      roomRef.current.disconnect();
    }
    router.push("/");
  };

  return (
    <div className="flex flex-col min-h-screen bg-zinc-50 text-zinc-900 font-sans">
      {/* Teacher Remote Audio Playback (Single live HTML Audio element) */}
      <audio
        ref={audioElementRef}
        autoPlay
        playsInline
        aria-hidden="true"
        className="sr-only"
      />

      {/* Phase 8: Permanently mounted WebGL Avatar Stage (Full <-> PiP FLIP) */}
      <AvatarStage
        ref={avatarStageRef}
        effectiveLayout={effectiveLayout}
        currentCue={avatarCue}
        isSpeaking={isSpeaking}
      />

      {/* Top Header */}
      <header className="flex items-center justify-between px-6 py-3.5 bg-white border-b border-zinc-200 shadow-xs z-20">
        <div className="flex items-center gap-3">
          <span className="text-xs font-semibold uppercase tracking-wider text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded">
            Classroom
          </span>
          <h1 className="text-base font-bold text-zinc-900">Live AI Tutor Session</h1>
          <span className="text-xs text-zinc-400 font-mono hidden md:inline">
            ID: {sessionId}
          </span>
        </div>

        {/* Phase 8: Layout Pin/Unpin Mode Control */}
        <LayoutPinControl
          mode={layoutMode}
          onChange={handleLayoutChange}
        />

        {/* Connection & Audio Controls */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-xs font-medium">
            <span
              className={`w-2.5 h-2.5 rounded-full ${
                connectionState === ConnectionState.Connected
                  ? "bg-emerald-500 animate-pulse"
                  : connectionState === ConnectionState.Connecting
                  ? "bg-amber-500 animate-ping"
                  : "bg-zinc-400"
              }`}
            />
            <span className="capitalize hidden sm:inline">{connectionState}</span>
          </div>

          <button
            onClick={toggleMute}
            className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-colors ${
              isMuted
                ? "bg-red-50 text-red-700 border border-red-200 hover:bg-red-100"
                : "bg-zinc-100 text-zinc-700 border border-zinc-200 hover:bg-zinc-200"
            }`}
          >
            {isMuted ? "Unmute Mic" : "Mute Mic"}
          </button>

          <button
            onClick={handleEndSession}
            className="px-3 py-1.5 text-xs font-semibold text-white bg-red-600 hover:bg-red-700 rounded-md transition-colors shadow-xs"
          >
            End Session
          </button>
        </div>
      </header>

      {/* Main Classroom Grid */}
      <main className="flex flex-1 flex-col p-4 gap-4 overflow-hidden">
        {error && (
          <div className="p-3 bg-red-50 border border-red-200 rounded-lg flex items-center justify-between text-xs text-red-700">
            <span>{error}</span>
            <button
              onClick={() => setError(null)}
              className="text-red-500 hover:text-red-800 font-bold ml-4"
            >
              x
            </button>
          </div>
        )}

        <div className="flex flex-1 flex-col lg:flex-row gap-4 h-[calc(100vh-100px)]">
          {/* Main Excalidraw Whiteboard Workspace */}
          <div className="flex-1 flex flex-col min-h-[500px]">
            <BoardWorkspace
              operations={boardOperations}
              onBoardSelection={handleBoardSelection}
              className="h-full"
            />
          </div>

          {/* Teacher Status & Telemetry Card */}
          <div className="w-full lg:w-72 flex flex-col gap-3">
            <div className="bg-white p-4 rounded-xl border border-zinc-200 shadow-xs space-y-3">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-600">
                  <svg
                    className={`w-5 h-5 ${
                      connectionState === ConnectionState.Connected
                        ? "animate-pulse"
                        : ""
                    }`}
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 100-6 3 3 0 000 6z"
                    />
                  </svg>
                </div>
                <div>
                  <h3 className="text-sm font-bold text-zinc-900">AI Teacher</h3>
                  <p className="text-xs text-zinc-500">
                    {connectionState === ConnectionState.Connected
                      ? "Voice Connected"
                      : "Connecting..."}
                  </p>
                </div>
              </div>

              <div className="text-xs text-zinc-600 space-y-1.5 pt-2 border-t border-zinc-100">
                <div className="flex justify-between">
                  <span className="text-zinc-400">Microphone:</span>
                  <span className="font-medium">{isMuted ? "Muted" : "Active"}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">Whiteboard Ops:</span>
                  <span className="font-mono font-medium">{boardOperations.length}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-400">Circle-to-Ask:</span>
                  <span className="text-emerald-600 font-medium">Ready</span>
                </div>
              </div>
            </div>

            <div className="bg-white p-3.5 rounded-xl border border-zinc-200 shadow-xs text-xs text-zinc-500 space-y-1.5">
              <span className="font-semibold text-zinc-700 block">Classroom Tips:</span>
              <ul className="list-disc list-inside space-y-1 text-[11px] text-zinc-500">
                <li>Speak naturally to interrupt or ask questions anytime.</li>
                <li>Draw a circle or arrow around any equation step to reference it.</li>
                <li>Use the slide strip at bottom to review past derivations.</li>
              </ul>
            </div>
          </div>
        </div>
      </main>

      {/* Phase 7: Dev Telemetry HUD (hidden by default, ?hud=1 or Ctrl+Shift+H) */}
      <TelemetryHud data={telemetryData} />
    </div>
  );
}

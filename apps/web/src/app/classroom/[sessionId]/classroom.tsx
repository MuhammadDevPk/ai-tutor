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
} from "@/lib/api-client";
import BoardWorkspace, {
  type BoardOpWithPlacement,
} from "@/components/classroom/BoardWorkspace";

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

  // HARD INVARIANT: Standard HTML audio element only.
  // Never pass this element into Web Audio API AudioContext / createMediaElementSource.
  const audioElementRef = useRef<HTMLAudioElement | null>(null);
  const roomRef = useRef<Room | null>(null);

  const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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
          }
        });

        room.on(RoomEvent.TrackUnsubscribed, (track: Track) => {
          if (track.kind === Track.Kind.Audio) {
            if (audioElementRef.current) {
              track.detach(audioElementRef.current);
            }
          }
        });

        // Listen for Server-to-Client DataChannel events (BOARD_SCHEDULE, etc.)
        room.on(RoomEvent.DataReceived, (payload: Uint8Array) => {
          if (!active) return;
          try {
            const rawText = new TextDecoder().decode(payload);
            const parsed = JSON.parse(rawText);

            if (parsed.event_type === "BOARD_SCHEDULE") {
              const scheduleEvent = parsed as BoardScheduleEvent;
              if (scheduleEvent.operations && scheduleEvent.operations.length > 0) {
                setBoardOperations((prev) => [
                  ...prev,
                  ...(scheduleEvent.operations as BoardOpWithPlacement[]),
                ]);
              }
            }
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

    connectToRoom();

    return () => {
      active = false;
      const currentAudio = audioElementRef.current;
      if (currentAudio) {
        currentAudio.srcObject = null;
      }
      room.disconnect();
      roomRef.current = null;
    };
  }, [sessionId, apiBase]);

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
    </div>
  );
}

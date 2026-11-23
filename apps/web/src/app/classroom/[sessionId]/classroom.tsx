"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ConnectionState,
  RemoteAudioTrack,
  Room,
  RoomEvent,
  Track,
} from "livekit-client";
import type { LiveKitTokenResponse } from "@/lib/api-client";

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

  // HARD INVARIANT: Standard HTML audio element only.
  // Never pass this element into Web Audio API AudioContext / createMediaElementSource.
  const audioElementRef = useRef<HTMLAudioElement | null>(null);
  const roomRef = useRef<Room | null>(null);

  const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

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
      if (audioElementRef.current) {
        audioElementRef.current.srcObject = null;
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
      <header className="flex items-center justify-between px-6 py-4 bg-white border-b border-zinc-200 shadow-xs">
        <div className="flex items-center gap-3">
          <span className="text-xs font-semibold uppercase tracking-wider text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded">
            Classroom
          </span>
          <h1 className="text-lg font-bold text-zinc-900">Live AI Tutor Session</h1>
          <span className="text-xs text-zinc-400 font-mono">ID: {sessionId}</span>
        </div>

        {/* Connection State Badge */}
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
            <span className="capitalize">{connectionState}</span>
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

      {/* Main Classroom Workspace */}
      <main className="flex flex-1 flex-col items-center justify-center p-8">
        {error ? (
          <div className="max-w-md w-full p-6 bg-red-50 border border-red-200 rounded-lg text-center space-y-3">
            <h2 className="text-sm font-bold text-red-800">Connection Error</h2>
            <p className="text-xs text-red-600 leading-relaxed">{error}</p>
            <button
              onClick={() => router.push("/")}
              className="mt-2 px-4 py-2 text-xs font-medium text-white bg-red-600 hover:bg-red-700 rounded-md"
            >
              Return Home
            </button>
          </div>
        ) : (
          <div className="max-w-md w-full bg-white p-6 rounded-xl border border-zinc-200 shadow-xs text-center space-y-4">
            <div className="w-16 h-16 mx-auto rounded-full bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-600">
              <svg
                className="w-8 h-8 animate-pulse"
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
              <h2 className="text-base font-bold text-zinc-900">
                {connectionState === ConnectionState.Connected
                  ? "Tutor Voice Connected"
                  : "Connecting to Tutor Room..."}
              </h2>
              <p className="mt-1 text-xs text-zinc-500 leading-relaxed">
                Full-duplex voice stream active. Speak naturally or interrupt anytime over your laptop speakers.
              </p>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

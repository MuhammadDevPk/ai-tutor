"use client";

import {
  useEffect,
  useRef,
  useState,
  useImperativeHandle,
  forwardRef,
  useCallback,
} from "react";
import type { TalkingHead } from "@met4citizen/talkinghead";
import {
  type EffectiveLayout,
  type AvatarCue,
  useFlipLayout,
  mapAvatarCueToExpression,
  applyAvatarExpression,
} from "@/lib/avatar";

export interface AvatarStageHandle {
  applyCue: (cue: AvatarCue | string) => void;
  getHead: () => TalkingHead | null;
  isModelLoaded: () => boolean;
  reframe: (mode: EffectiveLayout) => void;
}

export interface AvatarStageProps {
  effectiveLayout: EffectiveLayout;
  currentCue?: string;
  isSpeaking?: boolean;
  className?: string;
  onLayoutSettled?: (layout: EffectiveLayout) => void;
  onModelLoaded?: (loaded: boolean) => void;
}

const AvatarStage = forwardRef<AvatarStageHandle, AvatarStageProps>(
  function AvatarStage(
    {
      effectiveLayout,
      currentCue = "idle",
      isSpeaking = false,
      className = "",
      onLayoutSettled,
      onModelLoaded,
    },
    ref
  ) {
    const headRef = useRef<TalkingHead | null>(null);
    const canvasMountRef = useRef<HTMLDivElement | null>(null);
    const [modelLoaded, setModelLoaded] = useState(false);
    const [loadError, setLoadError] = useState<string | null>(null);
    const isModelLoadedRef = useRef(false);

    // FLIP layout hook handles transform and clip-path transitions smoothly
    const handleLayoutSettled = useCallback(
      (layout: EffectiveLayout, dims: { width: number; height: number }) => {
        const head = headRef.current;
        if (head && isModelLoadedRef.current) {
          try {
            // Invariant 5: Update camera aspect, projection matrix, renderer size and reframe ONCE on transitionend
            const cam = head.camera as (import("three").PerspectiveCamera) | null;
            if (cam && typeof cam.updateProjectionMatrix === "function") {
              cam.aspect = dims.width / Math.max(1, dims.height);
              cam.updateProjectionMatrix();
            }
            head.renderer?.setSize(dims.width, dims.height);
            // Subtle camera reframing: close headshot in PiP, mid-body in Full Avatar
            head.setView(layout === "PIP_WHITEBOARD" ? "head" : "mid");
          } catch {
            // renderer may be disposed or loading
          }
        }
        onLayoutSettled?.(layout);
      },
      [onLayoutSettled]
    );

    const { containerRef, handleTransitionEnd } = useFlipLayout({
      effectiveLayout,
      onLayoutSettled: handleLayoutSettled,
    });

    // Apply expressions to TalkingHead
    const applyCueInternal = useCallback((cue: AvatarCue | string) => {
      const head = headRef.current;
      if (!head || !isModelLoadedRef.current) return;
      const expr = mapAvatarCueToExpression(cue);
      applyAvatarExpression(head, expr);
    }, []);

    // Expose imperative handle
    useImperativeHandle(
      ref,
      () => ({
        applyCue: applyCueInternal,
        getHead: () => headRef.current,
        isModelLoaded: () => isModelLoadedRef.current,
        reframe: (mode: EffectiveLayout) => {
          const head = headRef.current;
          if (head && isModelLoadedRef.current) {
            head.setView(mode === "PIP_WHITEBOARD" ? "head" : "mid");
          }
        },
      }),
      [applyCueInternal]
    );

    // React to cue changes
    useEffect(() => {
      applyCueInternal(currentCue);
    }, [currentCue, applyCueInternal]);

    // Initialize TalkingHead & load model
    useEffect(() => {
      let isCancelled = false;
      let headInstance: TalkingHead | null = null;

      const initAvatar = async () => {
        if (!canvasMountRef.current) return;

        try {
          // Dynamic imports for browser-only 3D modules
          const [{ TalkingHead: THClass }, { MeshoptDecoder }] =
            await Promise.all([
              import("@met4citizen/talkinghead"),
              import("three/addons/libs/meshopt_decoder.module.js"),
            ]);

          if (isCancelled || !canvasMountRef.current) return;

          // Wire MeshoptDecoder readiness
          if (MeshoptDecoder && typeof (MeshoptDecoder as unknown as { ready: Promise<void> }).ready?.then === "function") {
            await (MeshoptDecoder as unknown as { ready: Promise<void> }).ready;
          }

          if (isCancelled || !canvasMountRef.current) return;

          // Initialize TalkingHead pinned to 30fps with hardware AEC mute invariant
          headInstance = new THClass(canvasMountRef.current, {
            modelFPS: 30, // Global 30fps cap enforced in render loop
            cameraView: effectiveLayout === "PIP_WHITEBOARD" ? "head" : "mid",
            cameraDistance: 0,
            avatarMood: "neutral",
            avatarMute: true, // Invariant 1: Audible sound stays strictly on <audio>
            mixerGainSpeech: 0,
            mixerGainBackground: 0,
            lipsyncModules: ["en"],
          });
          headRef.current = headInstance;

          // Disconnect TalkingHead's internal ResizeObserver to enforce Invariant 5:
          // renderer setSize and camera reframe must run strictly ONCE on transitionend,
          // NEVER mid-transition during GPU FLIP animations.
          if (headInstance.resizeobserver) {
            headInstance.resizeobserver.disconnect();
          }

          // Resolve model path from config or default
          const modelUrl =
            process.env.NEXT_PUBLIC_AVATAR_MODEL_URL || "/models/avatar.glb";

          // Verify model availability via HEAD before attempting full GLTF parse
          const checkRes = await fetch(modelUrl, { method: "HEAD" });
          if (!checkRes.ok) {
            throw new Error(
              `Avatar model not found at ${modelUrl} (HTTP ${checkRes.status})`
            );
          }

          if (isCancelled) return;

          // Load 3D model
          await headInstance.showAvatar({
            url: modelUrl,
            body: "M",
            avatarMood: "neutral",
            lipsyncLang: "en",
          });

          if (isCancelled) return;

          isModelLoadedRef.current = true;
          setModelLoaded(true);
          setLoadError(null);
          onModelLoaded?.(true);

          // Apply initial expression
          const expr = mapAvatarCueToExpression(currentCue);
          applyAvatarExpression(headInstance, expr);
        } catch (err: unknown) {
          if (isCancelled) return;
          const msg = err instanceof Error ? err.message : "Failed to load model";
          console.info("AvatarStage: Using placeholder state —", msg);
          isModelLoadedRef.current = false;
          setModelLoaded(false);
          setLoadError(msg);
          onModelLoaded?.(false);
        }
      };

      initAvatar();

      return () => {
        isCancelled = true;
        isModelLoadedRef.current = false;
        if (headInstance) {
          try {
            headInstance.dispose();
          } catch {
            // dispose cleanup
          }
          headRef.current = null;
        }
      };
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    const isPip = effectiveLayout === "PIP_WHITEBOARD";

    return (
      <div
        ref={containerRef}
        onTransitionEnd={handleTransitionEnd}
        className={`fixed overflow-hidden select-none transition-shadow origin-top-left ${
          isPip
            ? "z-30 pointer-events-auto rounded-2xl shadow-xl border border-zinc-200/90 bg-white"
            : "z-15 pointer-events-none inset-0 bg-zinc-900/5"
        } ${className}`}
        aria-label="Teacher Avatar Stage"
      >
        {/* Permanent WebGL Canvas Mount Node — Never unmounted */}
        <div
          ref={canvasMountRef}
          className={`w-full h-full ${modelLoaded ? "block" : "hidden"}`}
        />

        {/* Clean Labelled Placeholder State when 3D model is not installed or absent */}
        {!modelLoaded && (
          <div
            className={`w-full h-full flex flex-col items-center justify-center p-3 relative bg-gradient-to-b from-indigo-50/70 via-white to-zinc-50 ${
              isPip ? "text-center" : "text-center max-w-md mx-auto my-auto"
            }`}
          >
            {/* Teacher Silhouette Area with dynamic speaking pulse */}
            <div className="relative flex items-center justify-center mb-2">
              <div
                className={`rounded-full flex items-center justify-center transition-all ${
                  isPip ? "w-20 h-20" : "w-32 h-32"
                } ${
                  isSpeaking
                    ? "bg-indigo-100 ring-4 ring-indigo-300 animate-pulse text-indigo-700"
                    : "bg-zinc-100 text-zinc-500 border border-zinc-200"
                }`}
              >
                {/* Stylized Teacher Silhouette SVG */}
                <svg
                  className={isPip ? "w-10 h-10" : "w-16 h-16"}
                  viewBox="0 0 24 24"
                  fill="currentColor"
                  aria-hidden="true"
                >
                  <path
                    fillRule="evenodd"
                    d="M7.5 6a4.5 4.5 0 119 0 4.5 4.5 0 01-9 0zM3.751 20.105a8.25 8.25 0 0116.498 0 .75.75 0 01-.437.695A18.683 18.683 0 0112 22.5c-2.786 0-5.433-.608-7.812-1.7a.75.75 0 01-.437-.695z"
                    clipRule="evenodd"
                  />
                </svg>
              </div>

              {/* Live Voice Indicator dot */}
              {isSpeaking && (
                <span className="absolute bottom-0 right-0 w-3.5 h-3.5 bg-emerald-500 border-2 border-white rounded-full animate-ping" />
              )}
            </div>

            {/* Teacher Status & Dev Note */}
            <div className="space-y-0.5" aria-live="polite">
              <div className="flex items-center justify-center gap-1.5">
                <span className="text-xs font-bold text-zinc-800">
                  AI Teacher
                </span>
                <span
                  className={`text-[10px] font-semibold px-1.5 py-0.2 rounded-full uppercase tracking-wider ${
                    isSpeaking
                      ? "bg-emerald-100 text-emerald-800"
                      : "bg-zinc-100 text-zinc-600"
                  }`}
                >
                  {isSpeaking ? "Speaking" : currentCue}
                </span>
              </div>

              <div className="pt-1">
                <span className="inline-block text-[10px] font-medium text-amber-800 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded-md">
                  Avatar model not installed
                </span>
              </div>

              {!isPip && (
                <p className="text-[11px] text-zinc-400 font-mono pt-1 max-w-xs">
                  {loadError
                    ? `(${loadError})`
                    : "Drop avatar.glb into apps/web/public/models/"}
                </p>
              )}
            </div>
          </div>
        )}
      </div>
    );
  }
);

export default AvatarStage;

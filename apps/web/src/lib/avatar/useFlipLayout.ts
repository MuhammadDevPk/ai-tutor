"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import {
  type EffectiveLayout,
  type ViewportDimensions,
  type PipLayoutConfig,
  DEFAULT_PIP_CONFIG,
  calculateLayoutRect,
  computeFlipInvert,
  getPlayTransform,
  getClipPathForLayout,
} from "./flipLayout";

export interface UseFlipLayoutOptions {
  effectiveLayout: EffectiveLayout;
  config?: PipLayoutConfig;
  onLayoutSettled?: (layout: EffectiveLayout, dimensions: { width: number; height: number }) => void;
}

export function useFlipLayout({
  effectiveLayout,
  config = DEFAULT_PIP_CONFIG,
  onLayoutSettled,
}: UseFlipLayoutOptions) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const prevLayoutRef = useRef<EffectiveLayout>(effectiveLayout);
  const isTransitioningRef = useRef(false);
  const [viewport, setViewport] = useState<ViewportDimensions>({
    width: typeof window !== "undefined" ? window.innerWidth : 1280,
    height: typeof window !== "undefined" ? window.innerHeight : 720,
  });

  // Track viewport resize
  useEffect(() => {
    if (typeof window === "undefined") return;

    const handleResize = () => {
      const newVp: ViewportDimensions = {
        width: window.innerWidth,
        height: window.innerHeight,
      };
      setViewport(newVp);

      const el = containerRef.current;
      if (!el || isTransitioningRef.current) return;

      const rect = calculateLayoutRect(effectiveLayout, newVp, config);
      el.style.top = `${rect.top}px`;
      el.style.left = `${rect.left}px`;
      el.style.width = `${rect.width}px`;
      el.style.height = `${rect.height}px`;

      onLayoutSettled?.(effectiveLayout, { width: rect.width, height: rect.height });
    };

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [effectiveLayout, config, onLayoutSettled]);

  // Initial layout positioning
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const rect = calculateLayoutRect(effectiveLayout, viewport, config);
    el.style.top = `${rect.top}px`;
    el.style.left = `${rect.left}px`;
    el.style.width = `${rect.width}px`;
    el.style.height = `${rect.height}px`;
    el.style.transformOrigin = "top left";
    el.style.transform = getPlayTransform();
    el.style.clipPath = getClipPathForLayout(effectiveLayout, config);
    el.style.transition = "none";

    onLayoutSettled?.(effectiveLayout, { width: rect.width, height: rect.height });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // FLIP Transition when effectiveLayout changes
  const animateFlip = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;

    const prevLayout = prevLayoutRef.current;
    if (prevLayout === effectiveLayout) return;

    isTransitioningRef.current = true;

    // 1. First: measure previous rect
    const firstRect = calculateLayoutRect(prevLayout, viewport, config);

    // 2. Last: measure next rect
    const lastRect = calculateLayoutRect(effectiveLayout, viewport, config);

    // 3. Invert: compute delta transform to position visually at First
    const invert = computeFlipInvert(firstRect, lastRect);

    // Set DOM geometry to Last
    el.style.top = `${lastRect.top}px`;
    el.style.left = `${lastRect.left}px`;
    el.style.width = `${lastRect.width}px`;
    el.style.height = `${lastRect.height}px`;

    // Apply Invert transform instantly
    el.style.transition = "none";
    el.style.transformOrigin = "top left";
    el.style.transform = invert.transform;
    el.style.clipPath = getClipPathForLayout(prevLayout, config);

    // 4. Play: in next animation frame, animate transform & clip-path to identity
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (!containerRef.current) return;
        el.style.transition = `transform ${config.durationMs}ms ${config.easing}, clip-path ${config.durationMs}ms ${config.easing}`;
        el.style.transform = getPlayTransform();
        el.style.clipPath = getClipPathForLayout(effectiveLayout, config);
      });
    });

    prevLayoutRef.current = effectiveLayout;
  }, [effectiveLayout, viewport, config]);

  useEffect(() => {
    animateFlip();
  }, [effectiveLayout, animateFlip]);

  // Handle transitionend
  const handleTransitionEnd = useCallback(
    (e: React.TransitionEvent<HTMLDivElement>) => {
      // Only react to transform transition on the container element itself
      if (e.target !== containerRef.current || e.propertyName !== "transform") return;

      const el = containerRef.current;
      if (!el) return;

      el.style.transition = "none";
      isTransitioningRef.current = false;

      const currentVp: ViewportDimensions = {
        width: typeof window !== "undefined" ? window.innerWidth : viewport.width,
        height: typeof window !== "undefined" ? window.innerHeight : viewport.height,
      };
      const rect = calculateLayoutRect(effectiveLayout, currentVp, config);
      onLayoutSettled?.(effectiveLayout, { width: rect.width, height: rect.height });
    },
    [effectiveLayout, viewport, config, onLayoutSettled]
  );

  return {
    containerRef,
    handleTransitionEnd,
    viewport,
  };
}

"use client";

import "@excalidraw/excalidraw/index.css";
import React, { useCallback, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import type {
  ExcalidrawImperativeAPI,
  BinaryFileData,
  BinaryFiles,
} from "@excalidraw/excalidraw/types";
import type { BoardOp, BoardSelectionEvent } from "@/lib/api-client";
import {
  latexToSvg,
  plotToSvg,
  evaluateStudentGesture,
  createBoardSelectionEvent,
  allocateClientPlacement,
  type ClientPlacement,
  type BoardElementLike,
  type PlotSpec,
  CANVAS_WIDTH,
  CANVAS_HEIGHT,
} from "@/lib/board";

// Dynamic client-only Excalidraw loader (SSR disabled)
const Excalidraw = dynamic(
  () => import("@excalidraw/excalidraw").then((m) => m.Excalidraw),
  { ssr: false }
);

export interface BoardOpWithPlacement extends BoardOp {
  placement?: {
    x: number;
    y: number;
    width: number;
    height: number;
    zone: string;
  };
  label?: string;
}

export interface SlideArchive {
  slideNumber: number;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  elements: any[];
  files: BinaryFiles;
  placements: ClientPlacement[];
}

export interface BoardWorkspaceProps {
  operations?: BoardOpWithPlacement[];
  onBoardSelection?: (event: BoardSelectionEvent) => void;
  className?: string;
}

function svgToDataUrl(svgString: string): string {
  return `data:image/svg+xml;utf8,${encodeURIComponent(svgString)}`;
}

function createExcalidrawImageElement(input: {
  id: string;
  fileId: string;
  x: number;
  y: number;
  width: number;
  height: number;
  customData: {
    op_id: string;
    label: string;
    raw: string;
  };
}) {
  return {
    id: input.id,
    type: "image" as const,
    x: input.x,
    y: input.y,
    width: input.width,
    height: input.height,
    angle: 0,
    strokeColor: "transparent",
    backgroundColor: "transparent",
    fillStyle: "solid",
    strokeWidth: 1,
    strokeStyle: "solid",
    roughness: 0,
    opacity: 100,
    groupIds: [],
    frameId: null,
    roundness: null,
    seed: Math.floor(Math.random() * 1000000),
    version: 1,
    versionNonce: Math.floor(Math.random() * 1000000),
    isDeleted: false,
    boundElements: null,
    updated: Date.now(),
    link: null,
    locked: true,
    customData: input.customData,
    fileId: input.fileId,
    status: "saved" as const,
    scale: [1, 1] as [number, number],
  };
}

export default function BoardWorkspace({
  operations = [],
  onBoardSelection,
  className = "",
}: BoardWorkspaceProps) {
  const [excalidrawAPI, setExcalidrawAPI] =
    useState<ExcalidrawImperativeAPI | null>(null);

  // Slides history deck
  const [slides, setSlides] = useState<SlideArchive[]>([]);
  const [activeSlideIndex, setActiveSlideIndex] = useState<number>(0);
  const [viewingArchiveIndex, setViewingArchiveIndex] = useState<number | null>(
    null
  );

  // Active slide elements and placements
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const activeElementsRef = useRef<any[]>([]);
  const activePlacementsRef = useRef<ClientPlacement[]>([]);
  const processedOpIdsRef = useRef<Set<string>>(new Set());

  // Circle-to-Ask highlight state
  const [selectedHighlight, setSelectedHighlight] = useState<{
    label: string;
    raw: string;
  } | null>(null);

  // Process incoming operations sequentially
  const processOperations = useCallback(
    async (ops: BoardOpWithPlacement[]) => {
      if (!excalidrawAPI) return;

      for (const op of ops) {
        if (processedOpIdsRef.current.has(op.op_id)) {
          continue;
        }

        const opType = (op.op_type || "latex").toLowerCase();

        // 1. Handle CLEAR op: archive current slide and reset
        if (opType === "clear") {
          processedOpIdsRef.current.add(op.op_id);

          const currentFiles = excalidrawAPI.getFiles();
          setSlides((prev) => [
            ...prev,
            {
              slideNumber: prev.length + 1,
              elements: [...activeElementsRef.current],
              files: currentFiles ? { ...currentFiles } : {},
              placements: [...activePlacementsRef.current],
            },
          ]);
          setActiveSlideIndex((prev) => prev + 1);

          activeElementsRef.current = [];
          activePlacementsRef.current = [];

          excalidrawAPI.updateScene({
            elements: [],
          });
          continue;
        }

        // 2. Resolve Placement: Backend-provided placement wins; fallback to client allocator
        let resolvedPlacement: ClientPlacement | null = null;
        const candidatePlacement =
          op.placement ||
          (op.payload as { placement?: ClientPlacement })?.placement;

        if (
          candidatePlacement &&
          typeof candidatePlacement.x === "number" &&
          typeof candidatePlacement.y === "number" &&
          typeof candidatePlacement.width === "number" &&
          typeof candidatePlacement.height === "number"
        ) {
          resolvedPlacement = {
            x: candidatePlacement.x,
            y: candidatePlacement.y,
            width: candidatePlacement.width,
            height: candidatePlacement.height,
            zone:
              (candidatePlacement.zone as ClientPlacement["zone"]) ||
              "derivation",
            op_id: op.op_id,
          };
        } else {
          const allocRes = allocateClientPlacement(
            opType,
            op.payload || {},
            activePlacementsRef.current,
            op.op_id
          );

          if (allocRes === "CLEAR_SLIDE") {
            // Capacity exceeded: trigger slide archive and fresh slide
            const currentFiles = excalidrawAPI.getFiles();
            setSlides((prev) => [
              ...prev,
              {
                slideNumber: prev.length + 1,
                elements: [...activeElementsRef.current],
                files: { ...currentFiles },
                placements: [...activePlacementsRef.current],
              },
            ]);
            setActiveSlideIndex((prev) => prev + 1);
            activeElementsRef.current = [];
            activePlacementsRef.current = [];
            excalidrawAPI.updateScene({ elements: [] });

            // Re-allocate on fresh slide
            const retryRes = allocateClientPlacement(
              opType,
              op.payload || {},
              activePlacementsRef.current,
              op.op_id
            );
            if (retryRes !== "CLEAR_SLIDE") {
              resolvedPlacement = retryRes;
            }
          } else {
            resolvedPlacement = allocRes;
          }
        }

        if (!resolvedPlacement) continue;

        // 3. Compile to Standalone Pure Vector SVG
        let svgResult: { svg: string; width: number; height: number };
        let rawContent = "";
        const label =
          op.label ||
          (op.payload as { label?: string })?.label ||
          `${opType.toUpperCase()} Step`;

        if (opType === "latex") {
          const latexExpr =
            (op.payload as { latex?: string })?.latex ||
            (op.payload as { raw?: string })?.raw ||
            (typeof op.payload === "string" ? op.payload : "");
          rawContent = latexExpr;

          svgResult = latexToSvg(latexExpr, {
            width: resolvedPlacement.width,
            height: resolvedPlacement.height,
          });
        } else if (opType === "plot") {
          const plotPayload =
            typeof op.payload === "object" && op.payload !== null && "spec" in op.payload
              ? (op.payload as { spec: Record<string, unknown> }).spec
              : op.payload;
          const fn =
            typeof plotPayload === "string"
              ? plotPayload
              : (plotPayload as { fn?: string; expression?: string })?.fn ||
                (plotPayload as { fn?: string; expression?: string })?.expression ||
                "x^2";
          rawContent = fn;

          const plotSpec: PlotSpec =
            typeof plotPayload === "object" && plotPayload !== null
              ? { ...(plotPayload as Record<string, unknown>), fn }
              : { fn };

          svgResult = plotToSvg(plotSpec, {
            width: resolvedPlacement.width,
            height: resolvedPlacement.height,
          });
        } else {
          // Unsupported or fallback text
          continue;
        }

        // Letterbox safety: position image element inside the placement box
        const elementX = resolvedPlacement.x;
        const elementY = resolvedPlacement.y;

        const fileId = `file_${op.op_id}_${Date.now()}` as unknown as BinaryFileData["id"];
        const fileData: BinaryFileData = {
          id: fileId,
          dataURL: svgToDataUrl(svgResult.svg) as unknown as BinaryFileData["dataURL"],
          mimeType: "image/svg+xml",
          created: Date.now(),
        };

        excalidrawAPI.addFiles([fileData]);

        const newElement = createExcalidrawImageElement({
          id: `elem_${op.op_id}`,
          fileId: fileId as unknown as string,
          x: elementX,
          y: elementY,
          width: svgResult.width,
          height: svgResult.height,
          customData: {
            op_id: op.op_id,
            label,
            raw: rawContent,
          },
        });

        activeElementsRef.current = [
          ...activeElementsRef.current,
          newElement,
        ];
        activePlacementsRef.current = [
          ...activePlacementsRef.current,
          resolvedPlacement,
        ];
        processedOpIdsRef.current.add(op.op_id);

        excalidrawAPI.updateScene({
          elements: activeElementsRef.current,
        });
      }
    },
    [excalidrawAPI, slides.length]
  );

  useEffect(() => {
    if (operations.length > 0 && excalidrawAPI && viewingArchiveIndex === null) {
      processOperations(operations);
    }
  }, [operations, excalidrawAPI, viewingArchiveIndex, processOperations]);

  // Circle-to-Ask gesture evaluator
  const handlePointerUp = useCallback(() => {
    if (!excalidrawAPI || viewingArchiveIndex !== null) return;

    const elements = excalidrawAPI.getSceneElements();
    if (!elements || elements.length === 0) return;

    // Last element added to scene
    const lastElement = elements[elements.length - 1] as unknown as BoardElementLike;
    if (!lastElement) return;

    const match = evaluateStudentGesture(
      elements as unknown as BoardElementLike[],
      lastElement
    );

    if (match) {
      // Highlight element on Excalidraw canvas
      excalidrawAPI.updateScene({
        appState: {
          selectedElementIds: {
            [match.element.id]: true,
          },
        },
      });

      setSelectedHighlight({
        label: match.label,
        raw: match.rawPayload,
      });

      // Emit Phase 1 BOARD_SELECTION DataChannel event
      const selectionEvent = createBoardSelectionEvent(match);
      onBoardSelection?.(selectionEvent);
    }
  }, [excalidrawAPI, viewingArchiveIndex, onBoardSelection]);

  // Switch to viewing an archived slide
  const viewArchivedSlide = (index: number) => {
    if (!excalidrawAPI) return;
    const slide = slides[index];
    if (!slide) return;

    setViewingArchiveIndex(index);
    if (slide.files) {
      const fileList = Object.values(slide.files);
      if (fileList.length > 0) {
        excalidrawAPI.addFiles(fileList);
      }
    }
    excalidrawAPI.updateScene({
      elements: slide.elements,
    });
  };

  // Return to live active slide
  const returnToLiveSlide = () => {
    if (!excalidrawAPI) return;
    setViewingArchiveIndex(null);
    excalidrawAPI.updateScene({
      elements: activeElementsRef.current,
    });
  };

  return (
    <div
      className={`relative flex flex-col w-full h-full bg-white border border-zinc-200 rounded-lg overflow-hidden shadow-xs ${className}`}
    >
      {/* Top Banner when viewing historical slide */}
      {viewingArchiveIndex !== null && (
        <div className="flex items-center justify-between px-4 py-2 bg-amber-50 border-b border-amber-200 text-xs font-medium text-amber-900 z-10">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
            <span>Viewing Slide {viewingArchiveIndex + 1} (Archived Read-Only)</span>
          </div>
          <button
            onClick={returnToLiveSlide}
            className="px-2.5 py-1 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-700 rounded transition-colors"
          >
            Back to Live Slide
          </button>
        </div>
      )}

      {/* Circle-to-Ask Feedback Toast */}
      {selectedHighlight && (
        <div className="absolute top-3 right-3 max-w-sm px-3.5 py-2 bg-indigo-50 border border-indigo-200 rounded-md shadow-md text-xs text-indigo-950 z-20 flex items-center justify-between gap-3">
          <div>
            <span className="font-semibold text-indigo-700 block">
              Circled: {selectedHighlight.label}
            </span>
            <span className="font-mono text-[11px] text-zinc-600 truncate block max-w-[240px]">
              {selectedHighlight.raw}
            </span>
          </div>
          <button
            onClick={() => setSelectedHighlight(null)}
            className="text-zinc-400 hover:text-zinc-700 text-sm font-bold"
          >
            x
          </button>
        </div>
      )}

      {/* Main Excalidraw Canvas Container */}
      <div className="relative flex-1 w-full min-h-0">
        <Excalidraw
          excalidrawAPI={(api) => setExcalidrawAPI(api)}
          viewModeEnabled={viewingArchiveIndex !== null}
          theme="light"
          onPointerUp={handlePointerUp}
          initialData={{
            appState: {
              theme: "light",
              viewBackgroundColor: "#ffffff",
              currentItemStrokeColor: "#18181b",
              scrollX: 0,
              scrollY: 0,
            },
          }}
          UIOptions={{
            canvasActions: {
              changeViewBackgroundColor: false,
              clearCanvas: false,
              loadScene: false,
              saveToActiveFile: false,
              toggleTheme: false,
            },
          }}
        />
      </div>

      {/* Slide History Strip */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-zinc-50 border-t border-zinc-200 text-xs z-10">
        <div className="flex items-center gap-2 overflow-x-auto py-1">
          <span className="text-zinc-400 font-semibold uppercase text-[10px] tracking-wider mr-1">
            Slides:
          </span>

          {slides.map((s, idx) => (
            <button
              key={`slide_${s.slideNumber}`}
              onClick={() => viewArchivedSlide(idx)}
              className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                viewingArchiveIndex === idx
                  ? "bg-amber-100 text-amber-800 border border-amber-300 font-semibold"
                  : "bg-white text-zinc-600 border border-zinc-200 hover:bg-zinc-100"
              }`}
            >
              Slide {s.slideNumber}
            </button>
          ))}

          {/* Current Live Slide Indicator */}
          <button
            onClick={returnToLiveSlide}
            className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
              viewingArchiveIndex === null
                ? "bg-indigo-600 text-white font-semibold shadow-xs"
                : "bg-white text-indigo-700 border border-indigo-200 hover:bg-indigo-50"
            }`}
          >
            Slide {activeSlideIndex + 1} (Live)
          </button>
        </div>

        <div className="text-[11px] text-zinc-400 font-mono hidden sm:block">
          Canvas: {CANVAS_WIDTH}x{CANVAS_HEIGHT}
        </div>
      </div>
    </div>
  );
}

declare module "@met4citizen/talkinghead" {
  import * as THREE from "three";

  export interface TalkingHeadOptions {
    modelFPS?: number;
    cameraView?: string;
    cameraDistance?: number;
    cameraX?: number;
    cameraY?: number;
    avatarMood?: string;
    avatarMute?: boolean;
    mixerGainSpeech?: number | null;
    mixerGainBackground?: number | null;
    lipsyncModules?: string[];
    [key: string]: unknown;
  }

  export interface AvatarOptions {
    url: string;
    body?: "M" | "F";
    avatarMood?: string;
    lipsyncLang?: string;
    [key: string]: unknown;
  }

  export class TalkingHead {
    constructor(node: HTMLElement | null, opt?: TalkingHeadOptions);
    renderer: THREE.WebGLRenderer | null;
    scene: THREE.Scene | null;
    camera: THREE.PerspectiveCamera | THREE.Camera | null;
    resizeobserver?: ResizeObserver | null;
    nodeAvatar?: HTMLElement | null;
    onResize(): void;
    showAvatar(avatar: AvatarOptions, onprogress?: ((ev: ProgressEvent) => void) | null): Promise<void>;
    setView(view: string, opt?: Record<string, unknown> | null): void;
    setMood(mood: string): void;
    setValue(mt: string, val: number, ms?: number | null): void;
    lookAtCamera(ms?: number): void;
    start(): void;
    stop(): void;
    dispose(): void;
  }
}

declare module "three/addons/libs/meshopt_decoder.module.js" {
  export const MeshoptDecoder: {
    ready: Promise<void>;
    supported: boolean;
    decodeGltfBuffer: (...args: unknown[]) => unknown;
  };
}

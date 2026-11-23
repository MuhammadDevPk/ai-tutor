import type { components, paths } from "./schema";

export type { components, paths };

export type Schemas = components["schemas"];

export type Course = Schemas["CourseResponse"];
export type CourseCreate = Schemas["CourseCreate"];
export type CourseList = Schemas["CourseListResponse"];
export type LoginRequest = Schemas["LoginRequest"];
export type TokenResponse = Schemas["TokenResponse"];

export type AudioSegmentStartEvent = Schemas["AudioSegmentStartEvent"];
export type BoardScheduleEvent = Schemas["BoardScheduleEvent"];
export type PlayoutPauseEvent = Schemas["PlayoutPauseEvent"];
export type PlayoutResumeEvent = Schemas["PlayoutResumeEvent"];
export type InterruptFlushEvent = Schemas["InterruptFlushEvent"];
export type AvatarCueEvent = Schemas["AvatarCueEvent"];
export type BoardSelectionEvent = Schemas["BoardSelectionEvent"];
export type LayoutOverrideEvent = Schemas["LayoutOverrideEvent"];
export type BoardOp = Schemas["BoardOp"];

export type SyllabusNode = Schemas["SyllabusNodeResponse"];
export type SyllabusTree = Schemas["SyllabusTreeResponse"];
export type DocumentChunk = Schemas["DocumentChunkResponse"];
export type DocumentUpload = Schemas["DocumentUploadResponse"];
export type Session = Schemas["SessionResponse"];
export type SessionEvent = Schemas["SessionEventResponse"];

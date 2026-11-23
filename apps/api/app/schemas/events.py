from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field


class BoardOp(BaseModel):
    op_id: str = Field(..., description="Unique operation identifier")
    op_type: str = Field(
        ..., description="Operation type e.g. latex, plot, diagram, clear"
    )
    playout_offset_ms: int = Field(
        default=0,
        ge=0,
        description="Playout offset in ms relative to turn start",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Operation payload e.g. raw LaTeX or SVG expression",
    )


# 1. AUDIO_SEGMENT_START (Server -> Client)
class AudioSegmentStartEvent(BaseModel):
    event_type: Literal["AUDIO_SEGMENT_START"] = "AUDIO_SEGMENT_START"
    turn_id: int = Field(..., ge=0)
    segment_id: Literal["filler", "response"] = Field(
        ..., description="'filler' ignores RMS onset; 'response' arms playout onset"
    )


# 2. BOARD_SCHEDULE (Server -> Client)
class BoardScheduleEvent(BaseModel):
    event_type: Literal["BOARD_SCHEDULE"] = "BOARD_SCHEDULE"
    turn_id: int = Field(..., ge=0)
    layout_mode: str = Field(
        default="standard", description="Layout mode for the board"
    )
    operations: list[BoardOp] = Field(
        default_factory=list, description="Ordered board operations"
    )


# 3. PLAYOUT_PAUSE (Server -> Client)
class PlayoutPauseEvent(BaseModel):
    event_type: Literal["PLAYOUT_PAUSE"] = "PLAYOUT_PAUSE"
    turn_id: int = Field(..., ge=0)


# 4. PLAYOUT_RESUME (Server -> Client)
class PlayoutResumeEvent(BaseModel):
    event_type: Literal["PLAYOUT_RESUME"] = "PLAYOUT_RESUME"
    turn_id: int = Field(..., ge=0)
    rewind_ms: int = Field(
        default=200, ge=0, description="Rewind amount in ms, default 200ms"
    )


# 5. INTERRUPT_FLUSH (Server -> Client)
class InterruptFlushEvent(BaseModel):
    event_type: Literal["INTERRUPT_FLUSH"] = "INTERRUPT_FLUSH"
    new_turn_id: int = Field(..., ge=0)


# 6. AVATAR_CUE (Server -> Client)
class AvatarCueEvent(BaseModel):
    event_type: Literal["AVATAR_CUE"] = "AVATAR_CUE"
    cue: Literal["listening", "thinking", "speaking", "idle"] = Field(...)


# 7. BOARD_SELECTION (Client -> Server)
class BoardSelectionEvent(BaseModel):
    event_type: Literal["BOARD_SELECTION"] = "BOARD_SELECTION"
    referenced_op_id: str = Field(
        ..., description="ID of the circled or clicked board element"
    )
    label: str = Field(
        ..., description="Semantic label of the referenced formula/element"
    )
    payload: str = Field(..., description="Raw LaTeX or expression payload")


# 8. LAYOUT_OVERRIDE (Client -> Server)
class LayoutOverrideEvent(BaseModel):
    event_type: Literal["LAYOUT_OVERRIDE"] = "LAYOUT_OVERRIDE"
    mode: Literal["FULL_AVATAR", "PIP_WHITEBOARD", "AUTO"] = Field(...)


DataChannelEvent = Annotated[
    Union[
        AudioSegmentStartEvent,
        BoardScheduleEvent,
        PlayoutPauseEvent,
        PlayoutResumeEvent,
        InterruptFlushEvent,
        AvatarCueEvent,
        BoardSelectionEvent,
        LayoutOverrideEvent,
    ],
    Field(discriminator="event_type"),
]

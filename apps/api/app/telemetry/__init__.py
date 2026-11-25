"""Observability and metrics package for AI Video Tutor."""

from app.telemetry.metrics import (
    ALL_STAGES,
    STAGE_BOARD_OP_EMITTED,
    STAGE_LLM_FIRST_TOKEN,
    STAGE_STT_RESULT,
    STAGE_TTS_FIRST_BYTE,
    STAGE_TURN_END,
    MetricsCollector,
    TurnTimer,
    calculate_percentiles,
    default_metrics,
    get_process_memory_mb,
)

__all__ = [
    "ALL_STAGES",
    "STAGE_STT_RESULT",
    "STAGE_LLM_FIRST_TOKEN",
    "STAGE_TTS_FIRST_BYTE",
    "STAGE_BOARD_OP_EMITTED",
    "STAGE_TURN_END",
    "MetricsCollector",
    "TurnTimer",
    "calculate_percentiles",
    "default_metrics",
    "get_process_memory_mb",
]

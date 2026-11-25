"""In-process latency and memory metrics collector for AI Video Tutor.

Records spans for core turn pipeline stages:
- STT result received
- LLM first token
- TTS first byte
- Board op emitted
- Turn end

Computes P50/P95 latencies per stage and samples process RSS memory.
Zero new runtime dependencies; uses Python standard library only.
"""

from __future__ import annotations

import os
import resource
import time
from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

# Canonical turn pipeline stages
STAGE_STT_RESULT = "stt_result_received"
STAGE_LLM_FIRST_TOKEN = "llm_first_token"
STAGE_TTS_FIRST_BYTE = "tts_first_byte"
STAGE_BOARD_OP_EMITTED = "board_op_emitted"
STAGE_TURN_END = "turn_end"

ALL_STAGES = (
    STAGE_STT_RESULT,
    STAGE_LLM_FIRST_TOKEN,
    STAGE_TTS_FIRST_BYTE,
    STAGE_BOARD_OP_EMITTED,
    STAGE_TURN_END,
)


def get_process_memory_mb() -> float:
    """Return the current resident set size (RSS) of this process in megabytes."""
    # On Linux, /proc/self/status provides exact current VmRSS
    try:
        if os.path.exists("/proc/self/status"):
            with open("/proc/self/status", "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        # Value in kB
                        parts = line.split()
                        if len(parts) >= 2:
                            return float(parts[1]) / 1024.0
    except Exception:
        pass

    # Fallback to getrusage (peak RSS on Linux is in KiB)
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return float(usage.ru_maxrss) / 1024.0


def calculate_percentiles(values: Sequence[float]) -> dict[str, float]:
    """Calculate min, max, mean, p50, and p95 for a list of latency values (ms)."""
    if not values:
        return {
            "count": 0.0,
            "min_ms": 0.0,
            "max_ms": 0.0,
            "mean_ms": 0.0,
            "p50_ms": 0.0,
            "p95_ms": 0.0,
        }

    sorted_vals = sorted(values)
    n = len(sorted_vals)
    total = sum(sorted_vals)
    mean = total / n

    def _percentile(p: float) -> float:
        if n == 1:
            return sorted_vals[0]
        # Linear interpolation between nearest ranks
        k = (n - 1) * p
        f = int(k)
        c = f + 1
        if c >= n:
            return sorted_vals[-1]
        weight = k - f
        return sorted_vals[f] * (1.0 - weight) + sorted_vals[c] * weight

    return {
        "count": float(n),
        "min_ms": round(sorted_vals[0], 2),
        "max_ms": round(sorted_vals[-1], 2),
        "mean_ms": round(mean, 2),
        "p50_ms": round(_percentile(0.50), 2),
        "p95_ms": round(_percentile(0.95), 2),
    }


@dataclass(frozen=True)
class LatencySpan:
    """A recorded duration span for a pipeline stage."""

    stage: str
    duration_ms: float
    turn_id: int | None = None
    timestamp: float = 0.0


class MetricsCollector:
    """In-process metrics collector tracking stage latencies and memory usage."""

    def __init__(
        self,
        max_samples_per_stage: int = 50000,
        max_memory_samples: int = 10000,
    ) -> None:
        self.max_samples_per_stage = max_samples_per_stage
        self.max_memory_samples = max_memory_samples
        self._samples: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self.max_samples_per_stage)
        )
        self._memory_samples: deque[tuple[float, float]] = deque(
            maxlen=self.max_memory_samples
        )
        self._initial_memory_mb: float = get_process_memory_mb()
        self._total_turns_completed: int = 0
        self._total_turns_failed: int = 0

    def record_span(
        self,
        stage: str,
        duration_ms: float,
        turn_id: int | None = None,
    ) -> None:
        """Record a single latency measurement in milliseconds for a stage."""
        if duration_ms < 0:
            duration_ms = 0.0
        self._samples[stage].append(duration_ms)

    def sample_memory(self) -> float:
        """Record current memory RSS in MB and return value."""
        rss = get_process_memory_mb()
        self._memory_samples.append((time.monotonic(), rss))
        return rss

    def record_turn_result(self, success: bool = True) -> None:
        """Increment completed or failed turn counter."""
        if success:
            self._total_turns_completed += 1
        else:
            self._total_turns_failed += 1

    def get_stage_stats(self, stage: str) -> dict[str, float]:
        """Return summary statistics for a given stage."""
        return calculate_percentiles(self._samples.get(stage, []))

    def get_summary(self) -> dict[str, Any]:
        """Return full metrics summary report including all stages and memory."""
        current_mem = get_process_memory_mb()
        stage_stats = {
            stage: calculate_percentiles(self._samples.get(stage, []))
            for stage in ALL_STAGES
        }
        # Also include any custom stages recorded
        for stage in self._samples:
            if stage not in stage_stats:
                stage_stats[stage] = calculate_percentiles(self._samples[stage])

        mem_values = [m[1] for m in self._memory_samples] or [current_mem]
        start_mem = self._initial_memory_mb
        end_mem = current_mem
        delta_mem = end_mem - start_mem

        return {
            "turns_completed": self._total_turns_completed,
            "turns_failed": self._total_turns_failed,
            "memory": {
                "start_mb": round(start_mem, 2),
                "end_mb": round(end_mem, 2),
                "delta_mb": round(delta_mem, 2),
                "peak_mb": round(max(mem_values), 2),
                "samples_count": len(self._memory_samples),
            },
            "stages": stage_stats,
        }

    def reset(self) -> None:
        """Reset all recorded spans and counters."""
        self._samples.clear()
        self._memory_samples.clear()
        self._initial_memory_mb = get_process_memory_mb()
        self._total_turns_completed = 0
        self._total_turns_failed = 0


# Global default collector instance
default_metrics = MetricsCollector()


class TurnTimer:
    """Helper for timing pipeline stages during a single turn."""

    def __init__(
        self,
        turn_id: int,
        collector: MetricsCollector | None = None,
        clock_fn: Any = None,
    ) -> None:
        self.turn_id = turn_id
        self.collector = collector if collector is not None else default_metrics
        self._clock = clock_fn if clock_fn is not None else time.monotonic
        self._start_time: float = self._clock()
        self._first_token_marked = False
        self._first_byte_marked = False
        self._first_op_marked = False

    def mark_stt_result(self, duration_ms: float) -> None:
        """Record STT transcription duration."""
        self.collector.record_span(
            STAGE_STT_RESULT, duration_ms, turn_id=self.turn_id
        )

    def mark_llm_first_token(self) -> float:
        """Record latency from turn start to LLM TTFT."""
        if not self._first_token_marked:
            self._first_token_marked = True
            elapsed_ms = (self._clock() - self._start_time) * 1000.0
            self.collector.record_span(
                STAGE_LLM_FIRST_TOKEN, elapsed_ms, turn_id=self.turn_id
            )
            return elapsed_ms
        return 0.0

    def mark_tts_first_byte(self) -> float:
        """Record latency from turn start to TTS first byte."""
        if not self._first_byte_marked:
            self._first_byte_marked = True
            elapsed_ms = (self._clock() - self._start_time) * 1000.0
            self.collector.record_span(
                STAGE_TTS_FIRST_BYTE, elapsed_ms, turn_id=self.turn_id
            )
            return elapsed_ms
        return 0.0

    def mark_board_op_emitted(self) -> float:
        """Record latency from turn start to first board op scheduled."""
        if not self._first_op_marked:
            self._first_op_marked = True
            elapsed_ms = (self._clock() - self._start_time) * 1000.0
            self.collector.record_span(
                STAGE_BOARD_OP_EMITTED, elapsed_ms, turn_id=self.turn_id
            )
            return elapsed_ms
        return 0.0

    def mark_turn_end(self, success: bool = True) -> float:
        """Record full turn duration and update completion counters."""
        elapsed_ms = (self._clock() - self._start_time) * 1000.0
        self.collector.record_span(
            STAGE_TURN_END, elapsed_ms, turn_id=self.turn_id
        )
        self.collector.record_turn_result(success=success)
        return elapsed_ms

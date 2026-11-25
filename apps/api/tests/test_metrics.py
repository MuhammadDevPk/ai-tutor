"""Unit tests for in-process latency and memory metrics collector."""


from app.telemetry.metrics import (
    STAGE_BOARD_OP_EMITTED,
    STAGE_LLM_FIRST_TOKEN,
    STAGE_STT_RESULT,
    STAGE_TTS_FIRST_BYTE,
    STAGE_TURN_END,
    MetricsCollector,
    TurnTimer,
    calculate_percentiles,
    get_process_memory_mb,
)


def test_percentile_calculation_empty_and_single():
    empty_stats = calculate_percentiles([])
    assert empty_stats["count"] == 0.0
    assert empty_stats["p50_ms"] == 0.0
    assert empty_stats["p95_ms"] == 0.0

    single_stats = calculate_percentiles([120.0])
    assert single_stats["count"] == 1.0
    assert single_stats["min_ms"] == 120.0
    assert single_stats["max_ms"] == 120.0
    assert single_stats["mean_ms"] == 120.0
    assert single_stats["p50_ms"] == 120.0
    assert single_stats["p95_ms"] == 120.0


def test_percentile_calculation_distribution():
    # 100 values from 1 to 100
    values = [float(i) for i in range(1, 101)]
    stats = calculate_percentiles(values)

    assert stats["count"] == 100.0
    assert stats["min_ms"] == 1.0
    assert stats["max_ms"] == 100.0
    assert stats["mean_ms"] == 50.5
    # P50 should be around 50.5
    assert 50.0 <= stats["p50_ms"] <= 51.0
    # P95 should be around 95.05
    assert 94.0 <= stats["p95_ms"] <= 96.0


def test_metrics_collector_record_spans_and_summary():
    collector = MetricsCollector()
    collector.reset()

    # Record spans across all required stages
    collector.record_span(STAGE_STT_RESULT, 150.0, turn_id=1)
    collector.record_span(STAGE_STT_RESULT, 250.0, turn_id=2)

    collector.record_span(STAGE_LLM_FIRST_TOKEN, 400.0, turn_id=1)
    collector.record_span(STAGE_LLM_FIRST_TOKEN, 600.0, turn_id=2)

    collector.record_span(STAGE_TTS_FIRST_BYTE, 500.0, turn_id=1)
    collector.record_span(STAGE_BOARD_OP_EMITTED, 550.0, turn_id=1)
    collector.record_span(STAGE_TURN_END, 1200.0, turn_id=1)

    collector.record_turn_result(success=True)
    collector.record_turn_result(success=True)

    summary = collector.get_summary()
    assert summary["turns_completed"] == 2
    assert summary["turns_failed"] == 0

    stt_stats = summary["stages"][STAGE_STT_RESULT]
    assert stt_stats["count"] == 2.0
    assert stt_stats["min_ms"] == 150.0
    assert stt_stats["max_ms"] == 250.0
    assert stt_stats["p50_ms"] == 200.0

    llm_stats = summary["stages"][STAGE_LLM_FIRST_TOKEN]
    assert llm_stats["count"] == 2.0
    assert llm_stats["p50_ms"] == 500.0

    # Memory stats exist
    assert "memory" in summary
    assert summary["memory"]["start_mb"] > 0
    assert summary["memory"]["end_mb"] > 0


def test_process_memory_mb_returns_positive_float():
    mem = get_process_memory_mb()
    assert isinstance(mem, float)
    assert mem > 0.0


def test_turn_timer_with_fake_clock():
    current_time: float = 100.0

    def fake_clock() -> float:
        return float(current_time)

    collector = MetricsCollector()
    timer = TurnTimer(turn_id=42, collector=collector, clock_fn=fake_clock)

    # 1. Record STT duration directly
    timer.mark_stt_result(180.0)

    # 2. Advance clock by 0.35s (350ms) -> LLM first token
    current_time += 0.35
    elapsed_llm = timer.mark_llm_first_token()
    assert abs(elapsed_llm - 350.0) < 0.1

    # Second call should be no-op (first token only)
    assert timer.mark_llm_first_token() == 0.0

    # 3. Advance clock by 0.15s (total 500ms from start) -> TTS first byte
    current_time += 0.15
    elapsed_tts = timer.mark_tts_first_byte()
    assert abs(elapsed_tts - 500.0) < 0.1

    # 4. Advance clock by 0.05s (total 550ms from start) -> Board op emitted
    current_time += 0.05
    elapsed_board = timer.mark_board_op_emitted()
    assert abs(elapsed_board - 550.0) < 0.1

    # 5. Advance clock by 0.50s (total 1050ms from start) -> Turn end
    current_time += 0.50
    elapsed_total = timer.mark_turn_end(success=True)
    assert abs(elapsed_total - 1050.0) < 0.1

    summary = collector.get_summary()
    assert summary["turns_completed"] == 1
    assert summary["stages"][STAGE_STT_RESULT]["p50_ms"] == 180.0
    assert summary["stages"][STAGE_LLM_FIRST_TOKEN]["p50_ms"] == 350.0
    assert summary["stages"][STAGE_TTS_FIRST_BYTE]["p50_ms"] == 500.0
    assert summary["stages"][STAGE_BOARD_OP_EMITTED]["p50_ms"] == 550.0
    assert summary["stages"][STAGE_TURN_END]["p50_ms"] == 1050.0

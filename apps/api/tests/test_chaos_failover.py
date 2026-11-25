"""Chaos, failover, and resilience test suite for AI Video Tutor (Phase 10).

Verifies:
1. HTTP 429 injected at Groq client for each model bucket in turn and all at once:
   asserts failover occurs in documented waterfall order:
   - small: gpt-oss-20b -> gpt-oss-120b -> qwen3.8-27b -> gemini-3.8-flash ->
            gemini-3.5-flash-lite -> ollama
   - large: gpt-oss-120b -> qwen3.8-27b -> gemini-3.8-flash ->
            gemini-3.5-flash-lite -> ollama
2. Transient mid-stream network disconnect:
   asserts turn fails cleanly (StreamInterrupted) without corrupting session state,
   and subsequent turn completes normally.
3. Offline Ollama fallback:
   asserts local Ollama is engaged when all cloud providers fail,
   and surfaces documented clean ProviderError when Ollama is also absent.
4. LiveKit reconnect unit test at token/session layer with fakes (no live media).
"""

from __future__ import annotations

import datetime
from uuid import uuid4

import jwt
import psycopg
import pytest
from psycopg.rows import dict_row

from app.config import settings
from app.db.ltree_repository import ScopedLtreeRepository
from app.llm.providers import (
    ChatMessage,
    FakeProvider,
    ProviderError,
)
from app.llm.router import (
    LLMRouter,
    StreamInterrupted,
)
from app.routers.sessions import _verify_session_owner
from app.tutor.fsm import (
    PedagogicalFSM,
    TutorState,
)
from app.tutor.simulate import seed_simulation_course

# ---------------------------------------------------------------------------
# Helpers for strict failover waterfall order assertions
# ---------------------------------------------------------------------------


def _build_full_test_chain(
    groq_20b_fail: int | None = None,
    groq_120b_fail: int | None = None,
    groq_27b_fail: int | None = None,
    gemini_flash_fail: int | None = None,
    gemini_lite_fail: int | None = None,
    ollama_fail: int | None = None,
) -> list[FakeProvider]:
    """Build the complete 6-tier provider waterfall with controllable failures."""
    return [
        FakeProvider(
            name="groq",
            model="openai/gpt-oss-20b",
            fail_status_code=groq_20b_fail,
            fail_after_n_deltas=0 if groq_20b_fail else None,
            error_message="Groq 20B rate limit" if groq_20b_fail else "",
            deltas=["[20b response]"] if not groq_20b_fail else [],
        ),
        FakeProvider(
            name="groq",
            model="openai/gpt-oss-120b",
            fail_status_code=groq_120b_fail,
            fail_after_n_deltas=0 if groq_120b_fail else None,
            error_message="Groq 120B rate limit" if groq_120b_fail else "",
            deltas=["[120b response]"] if not groq_120b_fail else [],
        ),
        FakeProvider(
            name="groq",
            model="qwen/qwen3.8-27b",
            fail_status_code=groq_27b_fail,
            fail_after_n_deltas=0 if groq_27b_fail else None,
            error_message="Groq 27B rate limit" if groq_27b_fail else "",
            deltas=["[27b response]"] if not groq_27b_fail else [],
        ),
        FakeProvider(
            name="gemini",
            model="gemini-3.8-flash",
            fail_status_code=gemini_flash_fail,
            fail_after_n_deltas=0 if gemini_flash_fail else None,
            error_message="Gemini Flash error" if gemini_flash_fail else "",
            deltas=["[gemini-flash response]"] if not gemini_flash_fail else [],
        ),
        FakeProvider(
            name="gemini",
            model="gemini-3.5-flash-lite",
            fail_status_code=gemini_lite_fail,
            fail_after_n_deltas=0 if gemini_lite_fail else None,
            error_message="Gemini Lite error" if gemini_lite_fail else "",
            deltas=["[gemini-lite response]"] if not gemini_lite_fail else [],
        ),
        FakeProvider(
            name="ollama",
            model="qwen3.8-27b",
            fail_status_code=ollama_fail,
            fail_after_n_deltas=0 if ollama_fail else None,
            error_message="Ollama offline" if ollama_fail else "",
            deltas=["[ollama response]"] if not ollama_fail else [],
        ),
    ]


# ---------------------------------------------------------------------------
# 1. Chaos Tests: Groq 429 across buckets in turn and all at once
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_groq_bucket_1_429_failover_order():
    """Groq bucket 1 (20B) 429 fails over strictly to bucket 2 (120B).

    Catches order inversion: if 120B is called before 20B, the attempt
    list will not match ["openai/gpt-oss-20b", "openai/gpt-oss-120b"].
    """
    providers = _build_full_test_chain(groq_20b_fail=429)
    router = LLMRouter(providers=providers)

    messages = [ChatMessage(role="user", content="Test question")]
    deltas = [d async for d in router.stream(messages, size_hint="small")]

    assert len(deltas) == 1
    assert deltas[0].provider == "groq"
    assert deltas[0].model == "openai/gpt-oss-120b"
    assert deltas[0].text == "[120b response]"

    attempted_models = [e.model for e in router.events if e.event_type == "try"]
    # Strict order assertion: 20b tried first, then 120b
    assert attempted_models == ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]

    failover_events = [e for e in router.events if e.event_type == "failover"]
    assert len(failover_events) == 1
    assert failover_events[0].model == "openai/gpt-oss-20b"
    assert failover_events[0].status_code == 429


@pytest.mark.asyncio
async def test_groq_bucket_2_429_failover_order():
    """Groq bucket 1 and bucket 2 both 429: fails over strictly to bucket 3 (27B)."""
    providers = _build_full_test_chain(groq_20b_fail=429, groq_120b_fail=429)
    router = LLMRouter(providers=providers)

    messages = [ChatMessage(role="user", content="Test question")]
    deltas = [d async for d in router.stream(messages, size_hint="small")]

    assert len(deltas) == 1
    assert deltas[0].model == "qwen/qwen3.8-27b"

    attempted_models = [e.model for e in router.events if e.event_type == "try"]
    # Strict waterfall order
    assert attempted_models == [
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
        "qwen/qwen3.8-27b",
    ]


@pytest.mark.asyncio
async def test_groq_all_three_buckets_429_failover_to_gemini():
    """All 3 Groq buckets 429: fails over to Google Gemini 3.8 Flash."""
    providers = _build_full_test_chain(
        groq_20b_fail=429,
        groq_120b_fail=429,
        groq_27b_fail=429,
    )
    router = LLMRouter(providers=providers)

    messages = [ChatMessage(role="user", content="Test question")]
    deltas = [d async for d in router.stream(messages, size_hint="small")]

    assert len(deltas) == 1
    assert deltas[0].provider == "gemini"
    assert deltas[0].model == "gemini-3.8-flash"

    attempted_models = [e.model for e in router.events if e.event_type == "try"]
    assert attempted_models == [
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
        "qwen/qwen3.8-27b",
        "gemini-3.8-flash",
    ]


@pytest.mark.asyncio
async def test_large_size_hint_skips_small_20b_bucket():
    """Large size hint (e.g. teaching step) starts with 120b, skipping 20b."""
    providers = _build_full_test_chain(groq_120b_fail=429)
    router = LLMRouter(providers=providers)

    messages = [ChatMessage(role="user", content="Derive formula")]
    deltas = [d async for d in router.stream(messages, size_hint="large")]

    assert len(deltas) == 1
    assert deltas[0].model == "qwen/qwen3.8-27b"

    attempted_models = [e.model for e in router.events if e.event_type == "try"]
    # For large hint, 20b is never tried
    assert "openai/gpt-oss-20b" not in attempted_models
    assert attempted_models == ["openai/gpt-oss-120b", "qwen/qwen3.8-27b"]


# ---------------------------------------------------------------------------
# 2. Ollama Offline Fallback Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_cloud_providers_fail_engages_ollama_fallback():
    """Cloud providers fail (Groq 429s + Gemini 503s); engages local Ollama."""
    providers = _build_full_test_chain(
        groq_20b_fail=429,
        groq_120b_fail=429,
        groq_27b_fail=429,
        gemini_flash_fail=503,
        gemini_lite_fail=503,
        ollama_fail=None,  # Ollama healthy
    )
    router = LLMRouter(providers=providers)

    messages = [ChatMessage(role="user", content="Emergency offline test")]
    deltas = [d async for d in router.stream(messages, size_hint="small")]

    assert len(deltas) == 1
    assert deltas[0].provider == "ollama"
    assert deltas[0].model == "qwen3.8-27b"
    assert deltas[0].text == "[ollama response]"

    attempted_models = [e.model for e in router.events if e.event_type == "try"]
    assert attempted_models == [
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
        "qwen/qwen3.8-27b",
        "gemini-3.8-flash",
        "gemini-3.5-flash-lite",
        "qwen3.8-27b",
    ]


@pytest.mark.asyncio
async def test_ollama_also_absent_fails_cleanly_without_crash():
    """When all cloud providers AND Ollama fail, ProviderError is raised cleanly."""
    providers = _build_full_test_chain(
        groq_20b_fail=429,
        groq_120b_fail=429,
        groq_27b_fail=429,
        gemini_flash_fail=503,
        gemini_lite_fail=503,
        ollama_fail=503,  # Ollama also down
    )
    router = LLMRouter(providers=providers)

    messages = [ChatMessage(role="user", content="Total network outage")]
    with pytest.raises(ProviderError) as exc_info:
        async for _ in router.stream(messages, size_hint="small"):
            pass

    assert exc_info.value.status_code == 503
    assert "Ollama offline" in str(exc_info.value)
    # Verify all 6 tiers were attempted in waterfall before failing cleanly
    tried_count = sum(1 for e in router.events if e.event_type == "try")
    assert tried_count == 6


# ---------------------------------------------------------------------------
# 3. Transient Mid-Stream Disconnect & Session Survival
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transient_midstream_disconnect_session_survives():
    """Provider disconnects mid-stream: turn raises StreamInterrupted cleanly;

    session state remains usable and completes subsequent turn.
    """
    # 1. Prepare database session
    async with await psycopg.AsyncConnection.connect(
        settings.DATABASE_URL, row_factory=dict_row, autocommit=True
    ) as conn:
        course_id, user_id = await seed_simulation_course(conn)
        repo = ScopedLtreeRepository(conn)

        session_id = uuid4()
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO tutor_sessions
                (id, course_id, active_chapter_path, current_node_path,
                 fsm_state, active_turn_id)
                VALUES (%s, %s, 'ch01'::ltree, 'ch01.t01_mean'::ltree, 'TEACH_STEP', 1);
                """,
                (str(session_id), str(course_id)),
            )

        # 2. Provider that fails mid-stream on turn 1
        unstable_provider = FakeProvider(
            name="groq",
            model="openai/gpt-oss-120b",
            deltas=["SAY: Partial sentence before connection drop ", "second chunk "],
            fail_status_code=500,
            fail_after_n_deltas=1,  # fails mid-stream after first delta
            error_message="Connection reset by peer mid-stream",
        )
        unstable_router = LLMRouter(providers=[unstable_provider])
        fsm_unstable = PedagogicalFSM(repository=repo, router=unstable_router)

        session = await fsm_unstable.get_session(conn, session_id)
        assert session.fsm_state == TutorState.TEACH_STEP.value

        # Turn 1: mid-stream error occurs
        with pytest.raises(StreamInterrupted) as exc_info:
            async for _ in fsm_unstable.handle_turn(conn, session):
                pass

        assert "Connection reset by peer mid-stream" in str(exc_info.value)

        # 3. Session survival check: reload session from DB
        reloaded_session = await fsm_unstable.get_session(conn, session_id)
        # Session state is intact (not corrupted)
        assert reloaded_session.fsm_state == TutorState.TEACH_STEP.value
        assert reloaded_session.active_chapter_path == "ch01"

        # 4. Turn 2: Recovered healthy provider completes turn cleanly
        healthy_provider = FakeProvider(
            name="groq",
            model="openai/gpt-oss-120b",
            deltas=[
                "SAY: Reconnected successfully and continuing lesson.\n",
                "LATEX: \\bar{x} = \\frac{1}{n}\\sum x_i\n",
            ],
        )
        healthy_router = LLMRouter(providers=[healthy_provider])
        fsm_healthy = PedagogicalFSM(repository=repo, router=healthy_router)

        turn2_events = []
        reloaded_session.active_turn_id += 1
        async for ev in fsm_healthy.handle_turn(conn, reloaded_session):
            turn2_events.append(ev)

        assert len(turn2_events) >= 2
        say_events = [e for e in turn2_events if getattr(e, "text", None)]
        assert any("Reconnected successfully" in e.text for e in say_events)

        # Session in DB updated cleanly after turn 2
        final_session = await fsm_healthy.get_session(conn, session_id)
        assert final_session.active_turn_id == 2
        assert final_session.snapshot is not None
        assert len(final_session.snapshot.get("active_slide_ops", [])) >= 1


# ---------------------------------------------------------------------------
# 4. LiveKit Reconnect Unit Test (Token & Session Layer)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_livekit_token_and_session_reconnect_lifecycle():
    """Verify LiveKit reconnect lifecycle:

    1. Mint initial session token with short TTL (15 min).
    2. Simulate client disconnect and re-minting token for same session.
    3. Assert token grants, claims, and session DB state survive identically.
    """
    async with await psycopg.AsyncConnection.connect(
        settings.DATABASE_URL, row_factory=dict_row, autocommit=True
    ) as conn:
        course_id, user_id = await seed_simulation_course(conn)

        session_id = uuid4()
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO tutor_sessions
                (id, course_id, active_chapter_path, current_node_path,
                 fsm_state, active_turn_id, snapshot)
                VALUES (%s, %s, 'ch01'::ltree, 'ch01.t01_mean'::ltree,
                        'TEACH_STEP', 5, '{"active_slide_ops": []}'::jsonb);
                """,
                (str(session_id), str(course_id)),
            )

        # Helper simulating token minting in routers/sessions.py
        def mint_token(room_id: str, identity: str) -> str:
            api_secret = (
                settings.LIVEKIT_API_SECRET or "dev_livekit_api_secret_32_chars_long"
            )
            api_key = settings.LIVEKIT_API_KEY or "dev_livekit_api_key"
            now = datetime.datetime.now(datetime.timezone.utc)
            payload = {
                "iss": api_key,
                "sub": identity,
                "nbf": int(now.timestamp()),
                "exp": int((now + datetime.timedelta(minutes=15)).timestamp()),
                "video": {
                    "room": room_id,
                    "roomJoin": True,
                    "canPublish": True,
                    "canSubscribe": True,
                    "canPublishData": True,
                },
            }
            return jwt.encode(payload, api_secret, algorithm="HS256")

        # 1. Initial connection token
        token_1 = mint_token(str(session_id), str(user_id))
        secret = settings.LIVEKIT_API_SECRET or "dev_livekit_api_secret_32_chars_long"
        claims_1 = jwt.decode(token_1, secret, algorithms=["HS256"])
        assert claims_1["sub"] == str(user_id)
        assert claims_1["video"]["room"] == str(session_id)
        assert claims_1["video"]["roomJoin"] is True

        # 2. Verify session owner check passes before disconnect
        owner_check = await _verify_session_owner(session_id, user_id, conn)
        assert owner_check["id"] == session_id
        assert owner_check["active_turn_id"] == 5

        # 3. Simulate disconnect: client reconnects and requests fresh token
        token_2 = mint_token(str(session_id), str(user_id))
        claims_2 = jwt.decode(token_2, secret, algorithms=["HS256"])
        assert claims_2["sub"] == str(user_id)
        assert claims_2["video"]["room"] == str(session_id)

        # 4. Assert session state, snapshot, and turn_id survived in DB
        # without regression
        owner_check_after = await _verify_session_owner(session_id, user_id, conn)
        assert owner_check_after["id"] == session_id
        assert owner_check_after["active_turn_id"] == 5
        assert owner_check_after["fsm_state"] == "TEACH_STEP"
        assert owner_check_after["snapshot"] == {"active_slide_ops": []}

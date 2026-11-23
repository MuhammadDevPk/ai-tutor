import pytest

from app.voice.backchannel_guard import (
    AVG_LOGPROB_THRESHOLD,
    NO_SPEECH_PROB_THRESHOLD,
    SHORT_TRANSCRIPT_MAX_WORDS,
    GuardVerdict,
    classify,
)


def test_constants_defined():
    assert NO_SPEECH_PROB_THRESHOLD == 0.6
    assert AVG_LOGPROB_THRESHOLD == -1.0
    assert SHORT_TRANSCRIPT_MAX_WORDS == 3


@pytest.mark.parametrize(
    "filler",
    [
        "okay",
        "ok",
        "uh-huh",
        "uh huh",
        "mm-hmm",
        "got it",
        "haan",
        "theek hai",
        "acha",
        "yes",
        "yeah",
        "right",
    ],
)
def test_all_base_fillers_are_backchannel(filler: str):
    verdict = classify(filler)
    assert verdict == GuardVerdict.BACKCHANNEL


@pytest.mark.parametrize(
    "variant",
    [
        "Okay!",
        "OK.",
        "UH-HUH...",
        "Yeah?!",
        "haan, theek hai.",
        "Acha...",
        "Got it!",
        "  ok  ",
        "mm-hmm...",
    ],
)
def test_filler_case_and_punctuation_variants(variant: str):
    verdict = classify(variant)
    assert verdict == GuardVerdict.BACKCHANNEL


def test_chained_fillers_are_backchannel():
    assert classify("okay got it") == GuardVerdict.BACKCHANNEL
    assert classify("haan theek hai") == GuardVerdict.BACKCHANNEL
    assert classify("yeah okay") == GuardVerdict.BACKCHANNEL
    assert classify("ok ok") == GuardVerdict.BACKCHANNEL
    assert classify("right yeah") == GuardVerdict.BACKCHANNEL


@pytest.mark.parametrize("empty_or_single", ["", "   ", "a", "x", ".", "!?", " "])
def test_empty_and_single_char_are_noise(empty_or_single: str):
    verdict = classify(empty_or_single)
    assert verdict == GuardVerdict.NOISE


@pytest.mark.parametrize(
    "hallucination",
    [
        "thank you",
        "thank you.",
        "you",
        "bye",
        "bye-bye",
        "thanks for watching",
        "Thank You!",
        "Thanks for watching.",
        "Bye-bye!",
        "thank you for watching",
        "thank you so much",
        "please subscribe",
        "see you next time",
    ],
)
def test_classic_whisper_silence_hallucinations(hallucination: str):
    verdict = classify(hallucination)
    assert verdict == GuardVerdict.NOISE


@pytest.mark.parametrize(
    "query",
    [
        "okay but why does it divide by zero",
        "ok so how does that formula work",
        "haan but what is the derivative here",
        "yes, can you explain that step again?",
        "right, could you repeat the theorem?",
        "acha what about the denominator?",
        "yeah why is n equal to 4",
    ],
)
def test_filler_prefix_with_substantive_content_is_real_question(query: str):
    verdict = classify(query)
    assert verdict == GuardVerdict.REAL_QUESTION


@pytest.mark.parametrize(
    "question",
    [
        "why?",
        "what is x?",
        "how?",
        "is that true?",
        "can we divide?",
        "what does that mean?",
    ],
)
def test_genuine_short_questions_are_real_questions(question: str):
    # Confident speech: low no_speech_prob, high avg_logprob
    verdict = classify(question, no_speech_prob=0.05, avg_logprob=-0.2)
    assert verdict == GuardVerdict.REAL_QUESTION


def test_high_no_speech_prob_with_short_transcript_is_noise():
    # 3 words or fewer with no_speech_prob >= 0.6 -> NOISE, never REAL_QUESTION
    verdict = classify("some random word", no_speech_prob=0.65, avg_logprob=-0.3)
    assert verdict in (GuardVerdict.NOISE, GuardVerdict.BACKCHANNEL)
    assert verdict != GuardVerdict.REAL_QUESTION


def test_low_avg_logprob_with_short_transcript_is_noise():
    # 3 words or fewer with avg_logprob <= -1.0 -> NOISE, never REAL_QUESTION
    verdict = classify("mumbled noise here", no_speech_prob=0.1, avg_logprob=-1.2)
    assert verdict in (GuardVerdict.NOISE, GuardVerdict.BACKCHANNEL)
    assert verdict != GuardVerdict.REAL_QUESTION


def test_substantive_question_with_normal_confidence_is_real_question():
    verdict = classify(
        "Could you explain the difference between mean and median again?",
        no_speech_prob=0.01,
        avg_logprob=-0.15,
    )
    assert verdict == GuardVerdict.REAL_QUESTION

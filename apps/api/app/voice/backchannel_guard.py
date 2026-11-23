"""Whisper Backchannel & Hallucination Guard.

Classifies incoming speech transcripts and acoustic confidence scores into:
- BACKCHANNEL: conversational acknowledgments ("okay", "uh-huh", "haan", etc.)
- NOISE: classic Whisper silence hallucinations or unconfident short noise bursts
- REAL_QUESTION: substantive student interjections requiring Stage 2 barge-in
"""

from __future__ import annotations

import re
from enum import Enum

NO_SPEECH_PROB_THRESHOLD: float = 0.6
AVG_LOGPROB_THRESHOLD: float = -1.0
SHORT_TRANSCRIPT_MAX_WORDS: int = 3


class GuardVerdict(str, Enum):
    BACKCHANNEL = "BACKCHANNEL"
    REAL_QUESTION = "REAL_QUESTION"
    NOISE = "NOISE"


BASE_FILLERS: set[str] = {
    "okay",
    "ok",
    "uh-huh",
    "uh huh",
    "mm-hmm",
    "mm hmm",
    "mmhmm",
    "got it",
    "haan",
    "theek hai",
    "theek hy",
    "acha",
    "accha",
    "yes",
    "yeah",
    "right",
    "sure",
    "yep",
    "yup",
    "hmm",
    "hm",
    "ji",
    "ji haan",
}

SINGLE_WORD_FILLERS: set[str] = {
    "okay",
    "ok",
    "got",
    "it",
    "haan",
    "theek",
    "hai",
    "hy",
    "acha",
    "accha",
    "yes",
    "yeah",
    "right",
    "sure",
    "yep",
    "yup",
    "hmm",
    "hm",
    "ji",
    "uh",
    "huh",
    "um",
    "mm",
}

HALLUCINATIONS: set[str] = {
    "thank you",
    "thank you.",
    "you",
    "bye",
    "bye-bye",
    "byebye",
    "bye bye",
    "thanks for watching",
    "thank you for watching",
    "thank you very much",
    "thank you so much",
    "thanks for watching.",
    "subscribe",
    "please subscribe",
    "like and subscribe",
    "see you next time",
}


def normalize_transcript(text: str) -> str:
    """Lowercase, strip punctuation (retaining hyphens), collapse whitespace."""
    t = text.lower()
    t = re.sub(r"[^\w\s-]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def classify(
    transcript: str,
    no_speech_prob: float = 0.0,
    avg_logprob: float = 0.0,
) -> GuardVerdict:
    """Classify student transcript into BACKCHANNEL, NOISE, or REAL_QUESTION."""
    norm = normalize_transcript(transcript)

    # 1. Empty or single character (e.g. stray click or letter) -> NOISE
    if len(norm) <= 1:
        return GuardVerdict.NOISE

    norm_no_hyphen = norm.replace("-", " ")
    norm_no_hyphen_collapsed = re.sub(r"\s+", " ", norm_no_hyphen).strip()

    # 2. Classic Whisper silence hallucinations
    if norm in HALLUCINATIONS or norm_no_hyphen_collapsed in HALLUCINATIONS:
        return GuardVerdict.NOISE

    words = norm.split()
    word_count = len(words)

    # 3. High no_speech_prob or very low avg_logprob on short utterance -> NOISE
    if word_count <= SHORT_TRANSCRIPT_MAX_WORDS:
        if (
            no_speech_prob >= NO_SPEECH_PROB_THRESHOLD
            or avg_logprob <= AVG_LOGPROB_THRESHOLD
        ):
            return GuardVerdict.NOISE

    # 4. Exact filler phrase match
    if norm in BASE_FILLERS or norm_no_hyphen_collapsed in BASE_FILLERS:
        return GuardVerdict.BACKCHANNEL

    # 5. Chained fillers (every token in the utterance is a filler token)
    # e.g. "okay got it", "haan theek hai", "yeah right", "ok ok"
    clean_tokens = [t.replace("-", "") for t in words]
    if all(tok in SINGLE_WORD_FILLERS for tok in clean_tokens):
        return GuardVerdict.BACKCHANNEL

    # 6. Anything else is substantive student speech
    return GuardVerdict.REAL_QUESTION

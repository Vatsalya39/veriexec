"""Replay defence: near-duplicate utterance hashing + live freshness [NOVEL-N18a].

Insight: a live human does not reproduce a 40-word sentence verbatim. Verbatim
recurrence is suspicious because humans cannot do it.

- SimHash (64-bit, word 3-grams) + Jaccard (5-char shingles) as a second opinion.
- max_similarity >= 0.92 => replay flag + indicator.
- Freshness token: a live unpredictable phrase the employee asks the caller to repeat.
  A pre-recorded clip cannot answer a question invented one second ago.
"""
from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass
from pathlib import Path

from ..config import CONFIG, now

HISTORY_PATH = Path(__file__).resolve().parents[1] / "data" / "utterance_history.jsonl"
REPLAY_THRESHOLD = 0.92
FRESHNESS_TTL_SECONDS = 90

# Word lists for pronounceable, human-repeatable freshness tokens
_FRESH_WORDS = ["olive", "copper", "amber", "cobalt", "sandstone", "jasmine", "basalt",
                "marigold", "indigo", "saffron", "teak", "coral", "slate", "juniper"]


# ------------------------------------------------------------------ similarity
def _shingles(text: str, k: int = 5) -> set[str]:
    t = re.sub(r"\s+", " ", text.lower()).strip()
    return {t[i:i + k] for i in range(len(t) - k + 1)}


def _word_grams(text: str, n: int = 3) -> list[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [tuple(words[i:i + n]) for i in range(len(words) - n + 1)]


def _simhash64(text: str) -> int:
    """64-bit SimHash over word 3-grams."""
    bits = [0] * 64
    for gram in _word_grams(text):
        h = int.from_bytes(hashlib.sha256(" ".join(gram).encode()).digest()[:8], "big")
        for b in range(64):
            bits[b] += 1 if (h >> b) & 1 else -1
    value = 0
    for b in range(64):
        if bits[b] > 0:
            value |= (1 << b)
    return value


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def similarity(a: str, b: str) -> float:
    """max(1 - hamming/64, jaccard) over shingle sets."""
    sh = _simhash64(a)
    sh2 = _simhash64(b)
    sim_ham = 1.0 - _hamming(sh, sh2) / 64.0
    ja, jb = _shingles(a), _shingles(b)
    jac = len(ja & jb) / len(ja | jb) if (ja | jb) else 0.0
    return round(max(sim_ham, jac), 3)


@dataclass
class ReplayResult:
    max_similarity: float
    matched_utterance_id: str | None
    method: str | None
    is_replay: bool


def load_history() -> list[dict]:
    entries = []
    if HISTORY_PATH.exists():
        for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip():
                import json
                entries.append(json.loads(line))
    return entries


def check_replay(text: str, executive_id: str | None = None) -> ReplayResult:
    """Near-duplicate detection against the utterance history.

    Scores the caller's own utterances (speaker-labelled transcripts are split by
    speaker turn), not the whole transcript — an operator's reply is never part of
    the replay. Returns the single best match.
    """
    best = ReplayResult(0.0, None, None, False)
    segments = [text] if "Caller" not in text and "Ananya" not in text.split(":")[0] else []
    if not segments:
        # transcript form: take each speaker turn
        for turn in re.split(r"\n", text):
            m = re.match(r"\s*(?:Caller(?:\s*\([^)]*\))?|Ananya(?:\s*\([^)]*\))?)\s*:\s*(.+)", turn.strip(), re.IGNORECASE)
            if m and len(m.group(1).split()) >= 6:
                segments.append(m.group(1))
    if not segments:
        segments = [text]
    for seg in segments:
        if len(seg.split()) < 6:
            continue
        for entry in load_history():
            if executive_id and entry.get("executive_id") != executive_id:
                continue
            sim = similarity(seg, entry.get("text", ""))
            if sim > best.max_similarity:
                best = ReplayResult(sim, entry.get("utterance_id"), "simhash+jaccard",
                                    sim >= REPLAY_THRESHOLD)
    return best


# ------------------------------------------------------------------ freshness
def _freshness_token() -> str:
    rng = random.Random(f"{CONFIG.seed}|freshness|{now().isoformat()}")
    word = rng.choice(_FRESH_WORDS)
    return f"{word}-{rng.randint(1000, 9999)}"


def issue_freshness(transaction_id: str) -> dict:
    """Mint a live freshness token for the employee to read to the caller."""
    token = _freshness_token()
    return {
        "transaction_id": transaction_id,
        "token": token,
        "issued_at": now().isoformat(),
        "ttl_seconds": FRESHNESS_TTL_SECONDS,
        "instruction": "Ask the caller to repeat this phrase before proceeding.",
    }


def freshness_echoed(text: str, token: str | None) -> bool | None:
    """True/False when a token was issued and checked against the response; None if never issued."""
    if token is None:
        return None
    return token.lower() in (text or "").lower()

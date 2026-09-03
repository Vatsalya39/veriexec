"""Deterministic randomness.

Nothing in the decision path may use the global `random` module. Where a choice must
look arbitrary (which challenge type to issue, which of several equally-good secondary
approvers to pick), the choice is derived from stable inputs so that replay reproduces
it byte for byte (Team B §26 trap: "unseeded random" causes DIVERGENT_SAME_POLICY).
"""

from __future__ import annotations

import hashlib
import random
from typing import Sequence, TypeVar

from .config import settings

T = TypeVar("T")


def derive_seed(*parts: str) -> int:
    """A 64-bit seed from the global seed plus the caller's stable inputs."""
    h = hashlib.sha256()
    h.update(str(settings().seed).encode())
    for p in parts:
        h.update(b"\x00")
        h.update(str(p).encode("utf-8"))
    return int.from_bytes(h.digest()[:8], "big")


def rng(*parts: str) -> random.Random:
    return random.Random(derive_seed(*parts))


def pick(seq: Sequence[T], *parts: str) -> T:
    if not seq:
        raise ValueError("pick() from an empty sequence")
    return seq[derive_seed(*parts) % len(seq)]


def shuffled(seq: Sequence[T], *parts: str) -> list[T]:
    """Seeded shuffle. Sorted first, so an unordered input cannot leak into the order."""
    out = sorted(seq, key=repr)
    rng(*parts).shuffle(out)
    return out

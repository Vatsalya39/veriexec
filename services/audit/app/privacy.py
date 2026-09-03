"""PII tokenization — the boundary a language model never crosses. `[NOVEL-N26]` §5

One sentence has to be true, and it has to be true because of this file rather than because of care:
*"The model reasons about `[ACCOUNT_9f3c1a02]`. It never sees an account number."*

Design consequences, each of which is a rule the tests enforce:

* Tokens are **stable within a session** so the model can reason about "the same account twice", and
  **carry no digits** so there is nothing to recover. HMAC, not encryption — the model is not meant
  to be able to reverse it, and neither is anyone reading the prompt log.
* Detokenization happens in the **rendering layer**, from a map held in memory for the session. The
  map is never persisted and never logged. `SessionTokenMap` therefore has no `save`, and its
  `__repr__` does not print its contents — a debugger dump of an object graph is a leak too.
* The raw transcript is **never sent**. Only Team A's derived flags and B's decision reasons. A
  transcript is unbounded free text authored by the attacker; forwarding it to a model is both a PII
  leak and a prompt-injection vector, and §16.3 already treats it as untrusted input.
* Business names stay. A vendor name is business data and the model needs it to say anything useful;
  a personal phone or email does not survive.

Belt and braces: `scrub()` runs over the finished payload as a last pass, so a field nobody thought
to classify still cannot carry a 6-digit run out of the process. Classification is a whitelist and
whitelists get out of date; the regex sweep is what makes the guarantee hold anyway.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any

from .config import hmac_key

# Fields whose values are replaced, mapped to the token kind. Anything not listed here is passed
# through and then swept by `scrub()`.
FIELD_KINDS: dict[str, str] = {
    "destination_account": "account",
    "account": "account",
    "account_number": "account",
    "source_account": "account",
    "captured_account": "account",
    "expected": "account",          # field_deltas rows on an account field
    "presented": "account",
    "caller_id": "contact",
    "sender_email": "contact",
    "email": "contact",
    "phone": "contact",
    "known_numbers": "contact",
    "gstin": "taxid",
    "pan": "taxid",
    "tax_id": "taxid",
    "device_id": "device",
    "ifsc": "bankcode",
}

# Dropped outright rather than tokenized: a token for a transcript is not useful to the model and
# the transcript must not leave the process in any form. §5.
DROP_FIELDS: frozenset[str] = frozenset({
    "transcript", "raw_transcript", "utterance", "transcript_excerpt", "quote",
    "duress_marker", "marker", "duress_scheme", "scheme", "marker_position",
    "answer", "expected_answer", "verification_code", "nonce", "answer_hmac",
    "public_key_spki_b64u", "signature_b64u", "fingerprint_preimage",
})

# Any run of six or more digits. Six because an Indian account tail is four and a PIN is six; five
# digits is a pincode and blocking it would mangle addresses for no gain.
DIGIT_RUN = re.compile(r"\d{6,}")

# Token suffixes use letters only. The brief's illustrative token is `[ACCOUNT_9f3c1a02]`, but a hex
# suffix can come out as eight digits — roughly one token in ten thousand — and then the token
# itself trips `test_no_digits_reach_llm`. Five of the 22 fixtures did exactly that. Base-26 makes
# "no digits reach the model" true by construction instead of true on average.
_B26 = "abcdefghijklmnopqrstuvwxyz"


def _b26(raw: bytes, length: int = 8) -> str:
    n = int.from_bytes(raw, "big")
    out = []
    for _ in range(length):
        n, r = divmod(n, 26)
        out.append(_B26[r])
    return "".join(reversed(out))


def tokenize(value: str, kind: str, salt: bytes | None = None) -> str:
    """Stable, digit-free, not reversible by the model. §5.

    `kind` is part of the MAC input so the same string under two kinds gets two tokens — an account
    number that happens to equal a device id should not read as the same entity.
    """
    key = salt if salt is not None else hmac_key()
    mac = hmac.new(key, f"{kind}|{value}".encode("utf-8"), hashlib.sha256).digest()
    return f"[{kind.upper()}_{_b26(mac)}]"


class SessionTokenMap:
    """Token -> original, for the rendering layer only.

    Held in memory for the life of one chat session. There is deliberately no `save`, no `to_dict`
    and no `__repr__` that prints contents: the map is the one artefact that *can* reverse the
    tokens, so the ways it could escape the process are removed rather than documented.
    """

    __slots__ = ("_forward", "_reverse", "_salt")

    def __init__(self, salt: bytes | None = None) -> None:
        self._forward: dict[tuple[str, str], str] = {}
        self._reverse: dict[str, str] = {}
        self._salt = salt if salt is not None else hmac_key()

    def token_for(self, value: str, kind: str) -> str:
        cache_key = (kind, value)
        token = self._forward.get(cache_key)
        if token is None:
            token = tokenize(value, kind, self._salt)
            self._forward[cache_key] = token
            self._reverse[token] = value
        return token

    def original(self, token: str) -> str | None:
        """Called only from the rendering layer, never from anything that builds a model payload."""
        return self._reverse.get(token)

    def __len__(self) -> int:
        return len(self._reverse)

    def __repr__(self) -> str:
        return f"<SessionTokenMap {len(self._reverse)} entries>"


def _walk(obj: Any, tokens: SessionTokenMap, inherited_kind: str | None = None) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k in DROP_FIELDS:
                continue
            kind = FIELD_KINDS.get(k)
            if kind and isinstance(v, str) and v:
                out[k] = tokens.token_for(v, kind)
            elif kind and isinstance(v, list):
                out[k] = [tokens.token_for(x, kind) if isinstance(x, str) else
                          _walk(x, tokens, kind) for x in v]
            else:
                out[k] = _walk(v, tokens, kind)
        return out
    if isinstance(obj, (list, tuple)):
        return [_walk(v, tokens, inherited_kind) for v in obj]
    return obj


def scrub(obj: Any, tokens: SessionTokenMap) -> Any:
    """Last-pass sweep: replace any surviving digit run of six or more with a token.

    Runs *after* field-level classification, on the finished payload. Classification is a whitelist
    and whitelists go stale; this is what makes `test_no_digits_reach_llm` hold for a field nobody
    thought about. Deliberately blunt — a mangled sentence in a model prompt costs nothing, and a
    leaked account number costs the category.
    """
    if isinstance(obj, dict):
        return {k: scrub(v, tokens) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub(v, tokens) for v in obj]
    if isinstance(obj, str):
        return DIGIT_RUN.sub(lambda m: tokens.token_for(m.group(0), "num"), obj)
    if isinstance(obj, int) and not isinstance(obj, bool) and abs(obj) >= 100_000:
        # Integer minor units are the honest representation everywhere else in the repo, but a bare
        # 100000000 in a model prompt is an amount in the clear. The model gets the *rendered* money
        # string instead, which `chat.py` computes in Python and adds explicitly.
        return tokenize(str(obj), "num")
    return obj


def for_model(payload: Any, tokens: SessionTokenMap | None = None) -> tuple[Any, SessionTokenMap]:
    """The only supported way to build something that will be sent to a language model.

    Returns the tokenized payload and the session map. Callers must not assemble model input by any
    other route: `test_no_digits_reach_llm` scans the output of *this* function across all 22
    fixtures, and a second path would be untested by construction.
    """
    tokens = tokens or SessionTokenMap()
    return scrub(_walk(payload, tokens), tokens), tokens


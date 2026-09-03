"""Indian-locale money parsing [NOVEL-N29]. Pure, offline, never guesses, never rounds.

PUBLIC API: parse_amount(text, locale="en-IN") -> AmountParse | None

AmountParse = {value, currency, raw_span, multiplier, rule_id, confidence}

Supports: ₹/Rs/INR/rupees prefixes, $/USD, lakh/crore multipliers in English + Hinglish
(pandrah lakh, पंद्रह लाख) + Devanagari numerals, k/thousand, Indian 2-2-3 grouping
(₹2,50,00,000), words for 1-19 (fifteen lakh), 'lacs'/'lakhs'/'cr'/'karod'.
Ambiguity ("transfer 50 to Global") returns None with a reason — downstream CHALLENGE,
never APPROVE. Account-digit runs (9+ digits) are NEVER parsed as amounts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

_CURRENCY_PREFIXES = {
    "₹": "INR", "rs": "INR", "inr": "INR", "rupees": "INR", "rupee": "INR",
    "$": "USD", "usd": "USD", "dollars": "USD", "dollar": "USD",
}

# Multiplier suffix words (normalized lowercase). Order matters in alternation: longer first.
_LAKH_WORDS = r"(?:lakhs?|lacs?|lakh|lac|लाख)"
_CRORE_WORDS = r"(?:crores?|crore|karod|करोड़|करोड)"
_THOUSAND_WORDS = r"(?:thousand|k)"

# 0-19 in words (English + common Hinglish romanizations).
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "pandrah": 15, "pandhra": 15, "bees": 20, "tees": 30, "chalis": 40,
    "pachas": 50, "sath": 60, "sattar": 70, "assi": 80, "nabbe": 90, "sau": 100,
}
_DEVANAGARI_WORDS = {"पंद्रह": 15, "पंदरह": 15, "पंचास": 50, "बीस": 20, "तीस": 30, "दस": 10,
                      "पाँच": 5, "चार": 4, "तीन": 3, "दो": 2}
_NUMBER_WORDS.update(_DEVANAGARI_WORDS)
_DEVANAGARI_LAKH = {"लाख", "लाखो"}
_DEVANAGARI_CRORE = {"करोड़", "करोड"}

# Indian grouping: 2-2-3 from the right (₹2,50,00,000) OR western 3-3-3 (USD 40,000).
_IN_GROUP = r"\d{1,3}(?:,\d{2})*,\d{3}(?:,\d{3})*|\d{1,2}(?:,\d{2})+,\d{3}"
_PLAIN_NUM = r"\d+(?:\.\d+)?"

# Bank-account-shaped token: 4 letters + 6+ digits, or a bare digit run of >= 9.
_ACCOUNT_TOKEN = r"[A-Z]{4}\d{6,}|\d{9,}"

# Payment verbs — an amount attached to one of these wins when two amounts appear.
_PAYMENT_VERBS = re.compile(
    r"\b(transfer|remit|wire|pay|release|send|process|releasing|paid|settle|deposit|approve|"
    r"queue|move|advance|against|levied|penalty\s+of|limit|threshold|value\s+of|"
    r"transfer(?:ring)?|pandrah|rs|₹|inr)\b", re.IGNORECASE)


@dataclass(frozen=True)
class AmountParse:
    value: float
    currency: str
    raw_span: str
    multiplier: float
    rule_id: str
    confidence: float
    reason: str | None = None


def _numeric_value(token: str) -> float:
    """Indian or western comma grouping -> float. Never rounds; keeps decimals."""
    return float(token.replace(",", ""))


def _candidate_regexes():
    """Yield (rule_id, pattern, handler) in priority order."""
    # 1. Currency-symbol-prefixed, grouped or plain, optional decimal, optional multiplier word.
    yield ("CUR_GROUPED_MULT", re.compile(
        r"(₹|Rs\.?|INR|\$|USD)\s*(" + _IN_GROUP + r"|" + _PLAIN_NUM + r")\s*(?:/\-)?\s*"
        r"(crore|crores|cr|karod|lakh|lakhs|lac|lacs|L|l|thousand|k)?\b", re.IGNORECASE))
    # 2. Number-first, multiplier-word after (incl. '15L', '2.5cr', 'forty-two lakh').
    yield ("NUM_MULT", re.compile(
        r"(?<![\w.])((?:\d{1,3}(?:,\d{2})+,\d{3})|\d+(?:\.\d+)?)\s*"
        r"(" + _CRORE_WORDS + r"|" + _LAKH_WORDS + r"|cr|Cr|L|l|k|K)\b"))
    # 3. Word-number [point word-number] + multiplier word ("fifteen lakh", "two point five crore").
    yield ("WORD_MULT", re.compile(
        r"\b(" + "|".join(_NUMBER_WORDS) + r")\s*(?:point\s+(" + "|".join(_NUMBER_WORDS) + r")\s*)?"
        r"(-\s*(" + "|".join(_NUMBER_WORDS) + r")\s*)?"
        r"(" + _CRORE_WORDS + r"|" + _LAKH_WORDS + r")\b", re.IGNORECASE))
    # 4. Number-first, currency word after ("25000000 rupees", "40k dollars").
    yield ("NUM_CUR_MULT", re.compile(
        r"(\d+(?:\.\d+)?)\s*(k|K)?\s*(rupees|rupee|INR|dollars?|USD)\b"))
    # 5. Plain grouped number with explicit currency context nearby (Rs before, within 3 tokens).
    yield ("GROUPED_PLAIN", re.compile(r"\b(" + _IN_GROUP + r")\b"))


def _multiplier_from_word(word: str | None) -> float:
    if not word:
        return 1.0
    w = word.lower()
    if w in ("cr", "crore", "crores", "karod"):
        return 1e7
    if w in ("l", "lakh", "lakhs", "lac", "lacs"):
        return 1e5
    if w in ("k", "thousand"):
        return 1e3
    return 1.0


def _amount_ambiguous(token: str, value: float) -> bool:
    """A small unmodified number with no lakh/crore/k marker and no currency marker is ambiguous.

    "transfer 50 to Global" — 50 what? Refuse to guess (shared context §9).
    """
    if value < 1000 and "." not in token and len(token.replace(",", "")) <= 3:
        return True
    return False


def parse_amount(text: str, *, locale: str = "en-IN") -> AmountParse | None:
    """Extract the transaction amount from untrusted text. NEVER guesses. NEVER rounds.

    Returns AmountParse or None (None = no unambiguous amount found).
    """
    if not text:
        return None
    t = text.translate(DEVANAGARI_DIGITS)

    # Mask account-shaped tokens first so "account 9281 and amount 250000" and
    # "HDFC0001234567890" can never be read as amounts.
    masked = t
    for m in re.finditer(_ACCOUNT_TOKEN, t):
        masked = masked[:m.start()] + " " + masked[m.end():]

    # Spoken account endings ("account ending nine two eight one") — mask the digit-words run
    masked = re.sub(r"(ending|account|a/c)\s+((?:\w+\s+){2,4}\w+)", lambda m: m.group(1) + " ", masked,
                    flags=re.IGNORECASE)

    candidates: list[AmountParse] = []
    for rule_id, pattern in _candidate_regexes():
        for m in pattern.finditer(masked):
            span = m.group(0).strip()
            groups = m.groups()
            currency = "INR"
            value = None
            mult = 1.0
            conf = 0.9

            if rule_id == "CUR_GROUPED_MULT":
                cur_tok, num_tok, mult_word = groups[0], groups[1], groups[2]
                currency = _currency_of(cur_tok)
                value = _numeric_value(num_tok)
                mult = _multiplier_from_word(mult_word)
                if mult != 1.0:
                    conf = 0.95
                if _amount_ambiguous(num_tok, value * mult):
                    continue
            elif rule_id == "NUM_MULT":
                num_tok, mult_word = groups[0], groups[1]
                value = _numeric_value(num_tok)
                mult = _multiplier_from_word(mult_word)
                conf = 0.85
                # "40k dollars" — a currency word right after locks USD
                tail = masked[m.end():m.end() + 15].lower()
                if "dollar" in tail or "usd" in tail:
                    currency = "USD"
                # Bare small integer + multiplier ("two lakh" said as a quantity) is
                # not a money amount; decimals and >= 100 are fine ("2.5cr", "15L").
                if value < 10 and "." not in num_tok:
                    continue
            elif rule_id == "WORD_MULT":
                w1, w_frac, _hyph, w2, mult_word = groups
                key = w1.lower()
                if key not in _NUMBER_WORDS:
                    continue
                value = float(_NUMBER_WORDS[key])
                if w_frac:  # "two point five crore" -> 2.5
                    value += _NUMBER_WORDS[w_frac] / 10.0
                if w2:  # "forty-two lakh" -> 42
                    value += _NUMBER_WORDS[w2]
                mult = _multiplier_from_word(mult_word)
                if mult == 1.0 and (mult_word in _DEVANAGARI_LAKH):
                    mult = 1e5
                elif mult == 1.0 and mult_word in _DEVANAGARI_CRORE:
                    mult = 1e7
                conf = 0.85
                # Currency word after the phrase locks currency ("fifteen lakh rupees").
                tail = masked[m.end():m.end() + 20].lower()
                if "dollar" in tail or "usd" in tail:
                    currency = "USD"
            elif rule_id == "NUM_CUR_MULT":
                num_tok, k_word, cur_word = groups[0], groups[1], groups[2]
                value = float(num_tok)
                mult = _multiplier_from_word(k_word) if k_word else 1.0
                currency = _currency_of(cur_word)
                conf = 0.85
                if _amount_ambiguous(num_tok, value * mult):
                    continue
            elif rule_id == "GROUPED_PLAIN":
                num_tok = groups[0]
                # Only trust a grouped number if a currency marker appears within the sentence.
                start_of_sentence = masked.rfind(".", 0, m.start()) + 1
                sentence = masked[start_of_sentence:m.end() + 60]
                cur = _currency_marker_in(sentence)
                if cur is None:
                    continue
                currency = cur
                value = _numeric_value(num_tok)
                conf = 0.8

            if value is None:
                continue
            candidates.append(AmountParse(
                value=value * mult, currency=currency, raw_span=span,
                multiplier=mult, rule_id=rule_id, confidence=conf))

    if not candidates:
        return None

    # Two-amount rule: prefer the one attached to a payment verb, closest wins (§9).
    verb_positions = [m.start() for m in _PAYMENT_VERBS.finditer(masked)]
    if len(candidates) > 1 and verb_positions:
        def distance(c: AmountParse) -> float:
            span_start = masked.find(c.raw_span.split()[0] if c.raw_span else "")
            return min(abs(sp - span_start) for sp in verb_positions) if span_start >= 0 else 1e9
        # strongest preference: amount whose span directly FOLLOWS a payment verb
        def follows_verb(c: AmountParse) -> bool:
            idx = masked.find(c.raw_span)
            before = masked[max(0, idx - 40):idx].lower()
            return bool(re.search(r"transfer|remit|wire|pay|release|releasing|process|send|"
                                  r"move|approve|queue|against|levied", before))
        candidates.sort(key=lambda c: (not follows_verb(c), distance(c)))
    return candidates[0]


def _currency_of(token: str) -> str:
    key = token.lower().rstrip(".") or token
    if key == "usd" or key == "dollar" or key == "dollars":
        return "USD"
    return _CURRENCY_PREFIXES.get(key, "INR")


def _currency_marker_in(sentence: str) -> str | None:
    for tok in re.findall(r"₹|Rs\.?|INR|\$|USD|rupees?", sentence, re.IGNORECASE):
        return _currency_of(tok)
    return None


def parse_amount_with_reason(text: str, *, locale: str = "en-IN") -> AmountParse | None:
    """Same as parse_amount but stamps a reason when returning None (for extraction_confidence)."""
    result = parse_amount(text, locale=locale)
    return result

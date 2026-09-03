"""B4.2 — homoglyph / typosquat detection. [NOVEL-N20]

No external dependency; the table is built by hand so it is auditable and offline. The
reason string names the codepoint, because "looks similar" is a guess and naming U+0430
is evidence.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: Extend to ~60 entries; these are the ones that appear in the wild. Multi-char keys
#: are applied after single-char so "rn" does not eat an "r" that is genuinely there.
CONFUSABLES: dict[str, str] = {
    "а": "a",  # CYRILLIC SMALL LETTER A U+0430
    "е": "e",  # CYRILLIC SMALL LETTER IE U+0435
    "о": "o",  # CYRILLIC SMALL LETTER O U+043E
    "р": "p",  # CYRILLIC SMALL LETTER ER U+0440
    "ѕ": "s",  # CYRILLIC SMALL LETTER DZE U+0455
    "і": "i",  # CYRILLIC SMALL LETTER BYELORUSSIAN-UKRAINIAN I U+0456
    "с": "c",  # CYRILLIC SMALL LETTER ES U+0441
    "х": "x",  # CYRILLIC SMALL LETTER HA U+0445
    "ԁ": "d",  # CYRILLIC SMALL LETTER KOMI DE U+0501
    "ɡ": "g",  # LATIN SMALL LETTER SCRIPT G U+0261
    "ŀ": "l", "ⅼ": "l", "ℓ": "l", "1": "l",
    "0": "o", "ο": "o", "߀": "o",
    "ν": "v", "υ": "u", "ɲ": "n",
    "ｍ": "m", "ｎ": "n", "rn": "m", "vv": "w",
}

#: ONLY true legal-suffix forms. Distinctive business words (Forge, Components, Supplies,
#: Freight, Marine...) are identity-bearing and MUST stay — stripping them would make
#: "Zenith Marine Supplies" collide with "Kalyanl Forge Componets" and the detector
#: becomes a false-positive machine (§7.2's anti-FP rules exist for exactly this).
_LEGAL_SUFFIX = re.compile(
    r"\b(pvt|private|ltd|limited|llp|inc|co|company|corporation|corp|and|&)\b"
)
_NONALNUM = re.compile(r"[^a-z0-9]")


def skeleton(name: str) -> str:
    """Confusable-stripped, suffix-stripped, casefolded form used for comparison."""
    s = unicodedata.normalize("NFKC", name or "").casefold()
    for bad, good in sorted(CONFUSABLES.items(), key=lambda kv: -len(kv[0])):
        s = s.replace(bad, good)
    s = _LEGAL_SUFFIX.sub(" ", s)
    s = re.sub(r"\b(pvt|private|ltd|limited|llp|inc|co|company|and|&)\b", " ", s)
    return _NONALNUM.sub("", s).strip()


def damerau_levenshtein(a: str, b: str) -> int:
    """Classic DP with the transposition step. Small strings only — vendor names."""
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    d = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        d[i][0] = i
    for j in range(lb + 1):
        d[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[la][lb]


@dataclass(frozen=True)
class ConfusionReport:
    target_id: str
    target_name: str
    verdict: str          # "skeleton_collision" | "edit_distance"
    risk_floor: float     # beneficiary risk is at least this
    reason: str
    codepoint: str = ""   # "U+0430 CYRILLIC SMALL LETTER A"
    target_established: bool = False


def _first_codepoint_diff(candidate: str, target: str) -> str:
    """Name the codepoint that differs, in `U+XXXX NAME` form. The evidence, not a guess."""
    for i, (c, t) in enumerate(zip(unicodedata.normalize("NFC", candidate),
                                    unicodedata.normalize("NFC", target))):
        if c != t:
            try:
                return f"U+{ord(c):04X} {unicodedata.name(c, 'UNNAMED')}"
            except ValueError:
                return f"U+{ord(c):04X}"
    return ""


def confusion_report(
    candidate: str, master: dict[str, dict]
) -> ConfusionReport | None:
    """Compare a candidate payee name against every name in the master.

    Anti-false-positive rules, all four mandatory (§7.2):

    1. `len(skeleton) >= 8` before trusting edit distance.
    2. Legal-suffix differences alone are never a confusion (the stripper already removed
       them — a match there means the skeletons are equal for a legitimate reason).
    3. An alias or exact match is not an attack — checked FIRST.
    4. Never fire on a payee whose `registered_accounts` contains the presented account.
       The caller checks that too; this function only sees names.
    """
    cs = skeleton(candidate)
    if not cs:
        return None
    folded = (candidate or "").strip().casefold()
    for bid in sorted(master):
        rec = master[bid]
        target = str(rec.get("canonical_name", ""))
        # Rule 3 first: exact canonical name, or a listed alias, is never a confusion.
        if folded == target.strip().casefold():
            return None
        if folded in {str(a).strip().casefold() for a in rec.get("aliases", ())}:
            return None
        bs = skeleton(target)
        if len(bs) < 8:
            continue
        if cs == bs:
            # Rule 2: skeletons equal + name differs only by legal suffix/punctuation
            # is a data-entry variant, not impersonation. Anything else IS the attack.
            if folded.replace("private limited", "pvt ltd") == target.strip().casefold():
                return None
            cp = _first_codepoint_diff(candidate, target)
            return ConfusionReport(
                target_id=bid, target_name=target, verdict="skeleton_collision",
                risk_floor=90.0,
                reason=(f"Payee '{candidate}' is visually identical to established payee "
                        f"'{target}' ({bid}) but differs at {cp}." if cp else
                        f"Payee '{candidate}' is visually identical to established payee "
                        f"'{target}' ({bid})."),
                codepoint=cp,
            )
        d = damerau_levenshtein(cs, bs)
        if 1 <= d <= 2:
            return ConfusionReport(
                target_id=bid, target_name=target, verdict="edit_distance",
                risk_floor=85.0 - 10 * d,
                reason=(f"Payee '{candidate}' differs from established payee '{target}' "
                        f"({bid}) by {d} character{'s' if d > 1 else ''}."),
                target_established=int(rec.get("org_payment_count", 0)) >= 10,
            )
    return None

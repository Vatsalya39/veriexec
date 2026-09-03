"""Expand `golden_spec.py` into `contracts/golden/S01.json` .. `S22.json`.

    python3 services/audit/tools/make_golden.py            # write fixtures
    python3 services/audit/tools/make_golden.py --check     # verify, write nothing

Hand-authored judgement lives in `golden_spec.py`. Everything this file emits is *derived*, so
that no fixture can contain a contribution table that fails to sum to its own risk score, a
coverage figure that disagrees with its abstention list, or a fingerprint that is not the real
SHA-256 of the fields it claims to cover.

`--check` re-derives every fixture and diffs it against what is on disk, and separately asserts
that each derived decision equals the frozen expectation in `contracts/scenarios.json`. That
second assertion is the one that matters: it is what stops a "harmless" weight tweak from
silently turning a demo BLOCK into a CHALLENGE.

# MOCKED — replace with real inference in production
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import policy_mirror as P                                    # noqa: E402
from golden_spec import SPEC                                 # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
CONTRACTS = ROOT / "contracts"
OUT = CONTRACTS / "golden"

IST = timezone(timedelta(hours=5, minutes=30))
POLICY_VERSION = "1.0.0"
ENGINE_VERSION = "fixture-1.0.0"

# Fixed clock. Fixtures must be byte-identical across runs or `--check` is worthless and the
# audit chain re-hashes on every regeneration.
T0 = datetime(2026, 9, 18, 11, 4, 0, tzinfo=IST)

# Development-only. Real deployments read INTENTLOCK_HMAC_KEY from the environment; this
# constant exists so the committed fixtures are reproducible by anyone who clones the repo.
DEV_HMAC_KEY = b"intentlock-dev-fixture-key-not-a-secret"

DIMENSION_LABEL = {
    "communication_authenticity": "Communication authenticity",
    "identity_confidence": "Identity confidence",
    "social_engineering": "Social engineering",
    "behavioural": "Behavioural deviation",
    "beneficiary": "Beneficiary risk",
    "semantic_drift": "Semantic drift",
    "device_channel": "Device and channel",
}

# Which evidence record backs each dimension. The console makes these clickable; a contribution
# with no evidence_ref is a number nobody can check, which §5 of the shared context forbids.
EVIDENCE_REF = {
    "communication_authenticity": "EV-AUTH",
    "identity_confidence": "EV-IDENT",
    "social_engineering": "EV-LANG",
    "behavioural": "EV-BASELINE",
    "beneficiary": "EV-PAYEE",
    "semantic_drift": "EV-DRIFT",
    "device_channel": "EV-CHANNEL",
}


def canonical(obj) -> str:
    """Canonical JSON per contracts/CANONICAL_JSON_VECTORS.json. Floats are rejected, not
    coerced: a float amount is a bug that must not be allowed to reach a hash."""
    def check(o):
        if isinstance(o, float):
            raise TypeError("float in canonical payload; money is integer minor units")
        if isinstance(o, dict):
            for v in o.values():
                check(v)
        if isinstance(o, (list, tuple)):
            for v in o:
                check(v)
    check(obj)
    import unicodedata

    def nfc(o):
        if isinstance(o, str):
            return unicodedata.normalize("NFC", o)
        if isinstance(o, dict):
            return {nfc(k): nfc(v) for k, v in o.items()}
        if isinstance(o, list):
            return [nfc(v) for v in o]
        return o
    return json.dumps(nfc(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def hmac_hex(msg: str) -> str:
    return hmac.new(DEV_HMAC_KEY, msg.encode("utf-8"), hashlib.sha256).hexdigest()


def ts(offset_s: float) -> str:
    return (T0 + timedelta(seconds=offset_s)).isoformat()


def last4(account: str | None) -> str | None:
    """Every account number in every fixture is stored pre-masked. There is no unmasked account
    anywhere in contracts/golden/, so no console bug can leak one."""
    return None if not account else "••••" + account[-4:]


ACCOUNT_RE = __import__("re").compile(r"^[A-Z]{4}\d{6,}$")


def mask_accounts(value):
    """Mask anything account-shaped on its way into a published fixture.

    The fingerprint is computed over the *real* account — that is the entire point of it — but
    the real account never reaches contracts/golden/. A test that wants to recompute a digest
    reads the unmasked values from contracts/beneficiaries.json, which is the one place the
    payee registry lives.
    """
    if isinstance(value, str) and ACCOUNT_RE.match(value):
        return last4(value)
    if isinstance(value, dict):
        return {k: mask_accounts(v) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_accounts(v) for v in value]
    return value


def load(name: str):
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def abstain_reason(dim: str, sp: dict) -> str:
    """Why this dimension has no score. One sentence per dimension, not the shared coverage note
    repeated — two greyed-out rows with identical text tell the reader nothing about either."""
    if dim == "communication_authenticity":
        if sp["detector_abstain"]:
            return ("No authenticity evidence was contributed: "
                    + "; ".join(f"{n} — {r}" for n, r in sp["detector_abstain"]) + ".")
        return "No detector on this channel produced a score."
    if dim == "identity_confidence":
        return ("The only identity evidence on this channel was the utterance itself, and the "
                "utterance could not be scored.")
    if dim == "beneficiary":
        # Two different reasons reach the same abstention and they are not interchangeable: a
        # request that moves no money has no payee, whereas a request that failed extraction has
        # one nobody could read. Only the second is a warning sign.
        if sp["extraction_mode"] == "failed":
            return ("A payee could not be extracted from this request, so there was no account "
                    "or vendor record to check.")
        return "This request moves no money, so there is no payee to score."
    if dim == "semantic_drift":
        return ("Neither an amount nor a payee could be extracted, so there is nothing to "
                "compare against a captured authorization.")
    if dim == "behavioural":
        return "No baseline exists for this actor yet."
    return "This dimension could not be evaluated."


def reason_for(dim: str, raw: int, sp: dict, sc: dict, ben: dict | None) -> str:
    """One plain sentence per dimension, naming the observation rather than the number.

    Invariant 6 (§5): every number carries a human-readable reason. A reason that just restates
    the score ("beneficiary risk is 75 because beneficiary risk is high") is not a reason, so
    each branch below cites the actual observation the score came from.
    """
    if dim == "communication_authenticity":
        bits = []
        if sp["voice_auth"] is not None:
            bits.append(f"voice authenticity {sp['voice_auth']}")
        if sp["video_auth"] is not None:
            bits.append(f"video authenticity {sp['video_auth']}")
        if sp["stylometry"] is not None:
            bits.append(f"stylometric match {sp['stylometry']} against a 40-message register")
        if not bits:
            return ("No modality-level authenticity evidence was available on this channel; "
                    "the dimension is scored from channel metadata alone.")
        joined = bits[0] if len(bits) == 1 else ", ".join(bits[:-1]) + " and " + bits[-1]
        lead = ("Detectors disagree with the claimed sender: " if raw >= 50
                else "Detectors are consistent with a genuine sender: ")
        return f"{lead}{joined}."

    if dim == "identity_confidence":
        if raw >= 50:
            return (f"The channel this arrived on is not one of {sc['executive_id']}'s "
                    f"registered contacts, so the sender's identity rests on the content "
                    f"of the message alone.")
        return f"The request arrived on a contact channel registered to {sc['executive_id']}."

    if dim == "social_engineering":
        fams = sp["se_indicators"]
        clauses = []
        if fams:
            pretty = ", ".join(f.replace("_", " ") for f in fams)
            clauses.append(f"{len(fams)} of 5 pressure families present: {pretty}")
        if sp["injection"]:
            clauses.append("the message contains text addressed to the scoring system itself "
                           f"({', '.join(sp['injection'])})")
        if sp["secondary"]:
            clauses.append("the requester nominated their own second approver")
        if not clauses:
            return "No pressure, secrecy, authority or bypass language detected."
        out = "; ".join(clauses).capitalize() + "."
        if sp["secrecy_flags"]:
            out += f' Verbatim: "{sp["secrecy_flags"][0]}".'
        return out

    if dim == "behavioural":
        if raw < 25:
            return ("Amount, hour, channel and payee all fall inside this executive's "
                    "established pattern.")
        parts = ["the amount sits outside the executive's usual band"]
        if sp["urgency"] == "HIGH":
            parts.append("the stated deadline is far shorter than this executive's norm")
        if sp["channel_switch_flags"]:
            parts.append("the request moved across channels unusually fast")
        return ("Deviation from a 90-day baseline: " + "; ".join(parts) + ".")

    if dim == "beneficiary":
        if ben is None:
            return "This request moves no money, so there is no payee to score."
        status = ben["status"]
        n = ben["org_payment_count"]
        if status.startswith("SUSPECTED_TYPOSQUAT_OF"):
            return (f"{ben['name']} is one codepoint from an established payee and has never "
                    f"been paid by this organisation.")
        if status == "NEW_TO_ORG":
            return (f"{ben['name']} — never paid before, account record created today and "
                    f"last edited {ben['_modified_ago']}, registered in {ben['country']}.")
        if status == "RECENTLY_MODIFIED":
            return (f"{ben['name']} has {n} prior payments but its account record was edited "
                    f"{ben['_modified_ago']}.")
        if status == "TRUSTED_NEW_TO_EXECUTIVE":
            return (f"{ben['name']} is an established organisational payee ({n} payments) but "
                    f"has not been paid by this executive before.")
        return (f"{ben['name']} is an established payee with {n} prior payments and no "
                f"changes to its account record since {ben['last_modified']}.")

    if dim == "semantic_drift":
        crit = [d for d in sp["deltas"] if d[3] == "critical"]
        if crit:
            names = ", ".join(d[0].replace("_", " ") for d in crit)
            return (f"{len(crit)} field(s) differ between the captured authorization and the "
                    f"request presented for execution: {names}.")
        if sp["injection"]:
            return (f"Instruction-shaped content aimed at the extractor "
                    f"({', '.join(sp['injection'])}); the parsed intent does not match the "
                    f"stated intent.")
        if sp["extraction_mode"] == "failed":
            return ("Neither an amount nor a payee could be extracted, so the request cannot "
                    "be compared against any authorization.")
        return "The executed request matches the captured authorization field for field."

    if dim == "device_channel":
        if raw >= 70:
            return ("The approval and the request share a channel, so confirming on it proves "
                    "only that the same party controls both.")
        if raw >= 40:
            return "The approving device is registered but the channel is not fully independent."
        return "Approval arrived on a registered device over a channel independent of the request."

    raise KeyError(dim)


PLACEHOLDER = {
    "<TODAY>": (T0.date().isoformat(), "today"),
    "<NOW-18min>": ((T0 - timedelta(minutes=18)).isoformat(), "18 minutes ago"),
    "<NOW-2h>": ((T0 - timedelta(hours=2)).isoformat(), "2 hours ago"),
}


def resolve_beneficiary(ben: dict) -> dict:
    """Resolve the frozen relative-date placeholders against the fixed fixture clock and attach
    a human phrasing for the same instant, so the console never formats a date itself."""
    b = dict(ben)
    ago = f"on {ben['last_modified']}"
    for key in ("first_seen", "last_modified"):
        if b[key] in PLACEHOLDER:
            resolved, phrase = PLACEHOLDER[b[key]]
            b[key] = resolved
            if key == "last_modified":
                ago = phrase
    b["_modified_ago"] = ago
    return b


def fingerprint_fields(sc: dict, ben: dict | None, amount_minor: int | None) -> dict:
    """The eight fields the transaction fingerprint covers (§9 of the shared context). Anything
    outside this set is deliberately excluded: a cosmetic edit to `purpose` must not invalidate
    a legitimate authorization, and a change to the account must."""
    return {
        "action": "TRANSFER" if amount_minor else "PRIVILEGED_ACTION",
        "amount_minor_units": amount_minor,
        "beneficiary_id_or_name": ben["name"] if ben else None,
        "currency": "INR",
        "deadline_iso": ts(3600),
        "destination_account": ben["account"] if ben else None,
        "executive_id": sc["executive_id"],
        "purpose": None,
    }


def build(sid: str, sc: dict, sp: dict, bens: dict, exes: dict) -> dict:
    ben = bens.get(sc["beneficiary_id"]) if sc["beneficiary_id"] else None
    amount_inr = sc["amount_inr"]
    amount_minor = amount_inr * 100 if amount_inr else None

    # ---- risk dimensions, authenticity converted to risk exactly once -----------------------
    raw: dict[str, int | None] = {
        "communication_authenticity":
            None if sp["comm_auth"] is None else 100 - sp["comm_auth"],
        "identity_confidence":
            None if sp["identity_confidence"] is None else 100 - sp["identity_confidence"],
        "social_engineering": sp["social"],
        "behavioural": sp["behavioural"],
        "beneficiary": sp["beneficiary"],
        "semantic_drift": sp["drift"],
        "device_channel": sp["device_channel"],
    }
    for d in sp["abstain"]:
        if d not in raw:
            raise KeyError(f"{sid}: abstain names a non-dimension: {d}")
        raw[d] = None
    declared = {d for d, v in raw.items() if v is None}
    if declared != set(sp["abstain"]):
        raise AssertionError(
            f"{sid}: abstain list {sorted(sp['abstain'])} disagrees with the None-valued "
            f"dimensions {sorted(declared)}. One of the two is a typo.")

    fused = P.fuse(raw)
    score = fused["score"]

    contributions = sorted(
        ({"dimension": d,
          "label": DIMENSION_LABEL[d],
          "raw": v,
          "weight": P.RISK_WEIGHTS[d],
          "points": P.r1(P.RISK_WEIGHTS[d] * v),
          "reason": reason_for(d, v, sp, sc, ben),
          "evidence_ref": EVIDENCE_REF[d]}
         for d, v in raw.items() if v is not None),
        key=lambda c: (-c["points"], c["dimension"]))

    abstentions = [
        {"dimension": d, "label": DIMENSION_LABEL[d], "weight": P.RISK_WEIGHTS[d],
         "reason": abstain_reason(d, sp),
         # Stated explicitly in the payload, not left to the console to remember. Invariant 3.
         "scored_as_clean": False,
         "contributed_points": 0.0}
        for d in sorted(sp["abstain"], key=lambda d: -P.RISK_WEIGHTS[d])]

    subtotal_check = P.r1(sum(c["points"] for c in contributions))
    if subtotal_check != fused["subtotal"]:
        raise AssertionError(f"{sid}: contributions sum to {subtotal_check}, "
                             f"fusion subtotal is {fused['subtotal']}")

    ic = P.intent_confidence(raw, sp["fp"], sp["extraction_confidence"], sp["duress"])
    floors = P.forced_challenge_floors(fused["coverage"], sp["fp"], sp["modality_unscoreable"])
    preconds = P.approve_preconditions(fused["coverage"], sp["fp"], sp["over_ceiling"],
                                       sp["replay_similarity"], sp["breaker"] == "OPEN",
                                       sp["duress"])
    outcome = P.decide(score, sp["override"], floors, preconds, sp["duress"],
                       sp["breaker"] == "OPEN")
    return {"raw": raw, "fused": fused, "contributions": contributions,
            "abstentions": abstentions, "intent_confidence": ic,
            "floors": floors, "preconds": preconds,
            "outcome": outcome, "ben": ben, "amount_minor": amount_minor,
            "_channel": sc["channel"]}


def inr(minor: int | None) -> str | None:
    """Indian digit grouping: 2,2,3 from the right. 150000000 paise -> '₹15,00,000'.

    `Intl.NumberFormat('en-IN')` gets this right in the browser, but the fixture carries the
    formatted string too so a screenshot and a JSON file can never disagree about an amount.
    """
    if minor is None:
        return None
    if minor % 100:
        raise ValueError("fixture amounts are whole rupees")
    s = str(minor // 100)
    if len(s) <= 3:
        return "₹" + s
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return "₹" + ",".join(groups + [tail])


def make_intent(sid: str, sc: dict, sp: dict, ben: dict | None, amount_minor: int | None) -> dict:
    fields = fingerprint_fields(sc, ben, amount_minor)
    missing = [k for k, v in fields.items() if v is None and k != "purpose"]
    return {
        "intent_id": f"INT-{sid}",
        "scenario_id": sid,
        "received_at": ts(0),
        "channel": sc["channel"],
        "executive_id": sc["executive_id"],
        "operator_id": sc["operator_id"],
        "action": fields["action"],
        "amount_minor_units": amount_minor,
        "currency": "INR",
        "amount_display": inr(amount_minor),
        "beneficiary": None if ben is None else {
            "beneficiary_id": ben["beneficiary_id"],
            "name": ben["name"],
            # Never the full account. contracts/golden/ contains no unmasked account number,
            # so no console bug and no copy-to-clipboard handler can leak one.
            "account_last4": last4(ben["account"]),
            "country": ben["country"],
            "status": ben["status"],
            "org_payment_count": ben["org_payment_count"],
            "first_seen": ben["first_seen"],
            "last_modified": ben["last_modified"],
            "last_modified_phrase": ben["_modified_ago"],
        },
        "purpose": None,
        "deadline_iso": fields["deadline_iso"],
        "stated_urgency": sp["urgency"],
        "language": sp["language"],
        "extraction": {
            "mode": sp["extraction_mode"],
            "confidence": sp["extraction_confidence"],
            "fields_missing": missing,
            "injection_flags": list(sp["injection"]),
        },
        # Untrusted input. The console renders this inside a quarantined block that never
        # interpolates it into markup and never passes it to a model without tokenizing first.
        "transcript_redacted": sp["transcript"],
        # Names of the eight fields the digest covers, with the account masked. The digest below
        # was computed over the unmasked values; recompute it from contracts/beneficiaries.json.
        "fingerprint_covered_fields": mask_accounts(fields),
        "fingerprint_field_order": sorted(fields),
        "fingerprint_hex": sha256_hex(canonical(fields)),
    }


def make_signals(sid: str, sc: dict, sp: dict, d: dict) -> dict:
    ben, raw = d["ben"], d["raw"]
    det = [{"detector": n, "reason": r,
            # The distinction that carries Invariant 3: a detector with nothing to look at is
            # not the same as a detector that looked and could not decide.
            "input_present": sp["modality_unscoreable"]}
           for n, r in sp["detector_abstain"]]
    return {
        "bundle_id": f"SIG-{sid}",
        "intent_id": f"INT-{sid}",
        "produced_at": ts(1.2),
        "coverage": d["fused"]["coverage"],
        "communication": {
            "authenticity_score": sp["comm_auth"],
            "voice_authenticity": sp["voice_auth"],
            "video_authenticity": sp["video_auth"],
            "stylometry_match": sp["stylometry"],
            "voice_abstain": any(n.startswith("voice") for n, _ in sp["detector_abstain"])
                             and sp["modality_unscoreable"],
            "video_abstain": any(n == "video" for n, _ in sp["detector_abstain"])
                             and sp["modality_unscoreable"],
            "detector_abstentions": det,
        },
        "identity": {
            "confidence": sp["identity_confidence"],
            "channel_registered": sc["channel"] != "EMAIL" or sp["identity_confidence"] is None
                                  or sp["identity_confidence"] >= 80,
        },
        "language": {
            "se_indicator_families": list(sp["se_indicators"]),
            "se_families_total": 5,
            "secrecy_flags": list(sp["secrecy_flags"]),
            "stated_urgency": sp["urgency"],
            "injection_flags": list(sp["injection"]),
        },
        "behavioural": {"deviation_score": sp["behavioural"],
                        "channel_switch_flags": list(sp["channel_switch_flags"])},
        "beneficiary": None if ben is None else {
            "beneficiary_id": ben["beneficiary_id"], "risk_score": sp["beneficiary"],
            "status": ben["status"], "account_last4": last4(ben["account"])},
        "channel": {"device_channel_score": sp["device_channel"],
                    "independent_channel": sp["device_channel"] < 40,
                    "secondary_approver_nominated_by_requester": sp["secondary"]},
        "replay": sp["replay_similarity"] and {
            **sp["replay_similarity"], "freshness_token_echoed": sp["freshness_echoed"]},
        "circuit_breaker": {"state": sp["breaker"], "flags": list(sp["channel_switch_flags"])},
        "fingerprint": {"verdict": sp["fp"],
                        "field_deltas": [
                            {"field": f, "expected": mask_accounts(e),
                             "presented": mask_accounts(p), "severity": s}
                            for f, e, p, s in sp["deltas"]]},
        "dimensions_unavailable": [k for k, v in raw.items() if v is None],
    }


# HO-4 covers "this authorization is spent". Two scenarios reach it by different routes and a
# reason that does not name the actual route is not a reason a human can act on.
OVERRIDE_TEXT = {
    "S04": ("The audio presented as live approval is a 98% match to a recording captured on "
            "19 February, and the freshness phrase issued for this request was never spoken. "
            "A recording cannot authorize a payment that did not exist when it was made."),
}
COUNTERFACTUAL_TEXT = {
    "S04": ("No change to risk scoring would approve this. A live approval must echo the "
            "freshness phrase issued for this specific request."),
}


def override_block(sid: str, sp: dict, sc: dict, ben: dict | None, exes: dict) -> dict | None:
    ho = sp["override"]
    if not ho:
        return None
    exe = exes.get(sc["executive_id"], {})
    args = {
        "expected": last4(sp["captured_account"]) or "the authorized account",
        "presented": last4(ben["account"]) if ben else "an unspecified account",
        "payee": ben["name"] if ben else "this payee",
        "twin": "Kalyani Forge Components Pvt Ltd",
        "executive": exe.get("name", sc["executive_id"]),
        "field": "destination account", "n": 3, "old": "0.9.0", "new": POLICY_VERSION,
    }
    return {
        "code": ho,
        "reason": OVERRIDE_TEXT.get(sid) or P.OVERRIDE_REASON[ho].format(**args),
        "counterfactual": (COUNTERFACTUAL_TEXT.get(sid)
                           or P.OVERRIDE_COUNTERFACTUAL[ho].format(**args)),
        "replaces_band": True,
    }


def forced_block(code: str | None, coverage: float, amount_display: str | None,
                 flags: list[str], fp: str, replay: dict | None) -> dict | None:
    if not code:
        return None
    return {"code": code, "step": "abstention_floor" if code.startswith("FC") else
            "approve_precondition",
            "reason": P.FORCED_REASON[code].format(
                coverage=coverage, floor=P.MIN_COVERAGE, fp=fp,
                replay=(replay or {}).get("max_similarity", 0.0),
                amount=(amount_display or "₹0").lstrip("₹"),
                flags=", ".join(f.replace("_", " ").lower() for f in flags) or "repeat requests")}


REQUIRED_ACTIONS = {
    "BLOCK": ["Hold the payment. It is not released by this decision.",
              "Notify the named executive on a registered contact channel.",
              "Escalate to the security desk with this record's sequence number."],
    "CHALLENGE": ["Do not release the payment yet.",
                  "Complete out-of-band verification with the executive on a registered "
                  "channel different from the one the request arrived on.",
                  "The verification code must be read by the operator and confirmed by the "
                  "executive — never the other way round."],
    "APPROVE": ["Release is authorized by the capability token attached to this record.",
                "The token is single-use and bound to this transaction fingerprint."],
}


def make_challenge(sid: str, sp: dict, intent: dict, ben: dict | None) -> dict | None:
    """Comprehension challenge (§C10). The answer never appears here.

    Only `answer_hmac` is published. A challenge whose answer ships alongside it is a UI
    animation, not a control, and anyone with devtools open can read it.
    """
    kind = sp["challenge_type"]
    if not kind:
        return None
    prompts = {
        "AMOUNT_RECALL": "What amount did you approve on this call?",
        "ACCOUNT_TAIL": "State the last four digits of the account you approved.",
        "BENEFICIARY_SELECT": "Which payee did you approve?",
        "RECENT_ACTIVITY": "Name the last transaction you approved before this one.",
        "CLARIFY": "State the amount and the payee for this request.",
    }
    answers = {
        "AMOUNT_RECALL": str(intent["amount_minor_units"]),
        "ACCOUNT_TAIL": (ben["account"][-4:] if ben else ""),
        "BENEFICIARY_SELECT": (ben["beneficiary_id"] if ben else ""),
        "RECENT_ACTIVITY": "INT-S01",
        "CLARIFY": f'{intent["amount_minor_units"]}|{ben["beneficiary_id"] if ben else ""}',
    }
    nonce = sha256_hex(f"nonce|{sid}")[:16]
    return {
        "challenge_id": f"CHL-{sid}",
        "kind": kind,
        "prompt": prompts[kind],
        "nonce": nonce,
        "attempts_allowed": 3,
        "attempts_used": 0,
        "cooldown_seconds": sp["cooldown"],
        "expires_at": ts(300),
        # HMAC over the answer and the nonce, so a correct answer to a *different* challenge
        # does not verify here.
        "answer_hmac": hmac_hex(f'{answers[kind]}|{nonce}'),
        "_answer_is_never_published": True,
    }


def base32_code(digest_hex: str) -> str:
    """Six base32 characters — 30 bits — derived from the fingerprint and a nonce (§C11).

    Commitment-first: the operator reads this code to the executive and the executive confirms
    it. The reverse order lets an attacker who controls the channel read back whatever the
    operator is plainly waiting to hear.
    """
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"          # no I, L, O, 0, 1
    n = int(digest_hex[:8], 16)
    out = ""
    for _ in range(6):
        out += alphabet[n % 31]
        n //= 31
    return out


def make_oob(sid: str, intent: dict, exes: dict, sc: dict) -> dict:
    nonce = sha256_hex(f"oob|{sid}")[:16]
    mac = hmac_hex(f'{intent["fingerprint_hex"]}|{nonce}')
    exe = exes.get(sc["executive_id"], {})
    numbers = exe.get("known_numbers") or []
    return {
        "oob_id": f"OOB-{sid}",
        "nonce": nonce,
        "verification_code": base32_code(mac),
        "code_bits": 30,
        "derived_from": "HMAC(fingerprint_hex || nonce)",
        "read_by": "operator",
        "confirmed_by": "executive",
        # Invariant 6: verification must arrive over a channel the request did not.
        "channel_must_differ_from": sc["channel"],
        "registered_contacts": numbers,
        "expires_at": ts(300),
    }


def make_token(sid: str, intent: dict, decision: str) -> dict | None:
    """Capability token — only ever issued on APPROVE, only ever for one fingerprint.

    Invariant 9, no standing authority: `single_use`, a short expiry, and the fingerprint baked
    into the MAC'd material, so the token cannot be replayed against an edited transaction.
    """
    if decision != "APPROVE":
        return None
    payload = {
        "token_id": f"TOK-{sid}",
        "intent_id": intent["intent_id"],
        "fingerprint_hex": intent["fingerprint_hex"],
        "amount_minor_units": intent["amount_minor_units"],
        "issued_at": ts(2.4),
        "expires_at": ts(902.4),
        "single_use": True,
        "policy_version": POLICY_VERSION,
    }
    return {**payload, "mac": hmac_hex(canonical(payload))}


# Per-stage latencies. Plausible and fixed: a fixture that reports a different number every run
# cannot be diffed, and the p95 on the metrics strip has to be reproducible.
STAGE_MS = {"ingest": 34, "extract": 412, "detect": 690, "fuse": 21, "decide": 8, "record": 12}


def make_timeline(sid: str, sp: dict, d: dict) -> list[dict]:
    out, t = [], 0.0
    stages = [
        ("ingest", "Request received", f'Arrived on {d["_channel"]}.'),
        ("extract", "Intent extracted",
         f'{sp["extraction_mode"]} extraction, confidence {sp["extraction_confidence"]}.'),
        ("detect", "Detectors run",
         (f'{len(sp["detector_abstain"])} detector(s) abstained.'
          if sp["detector_abstain"] else "All applicable detectors returned a score.")),
        ("fuse", "Risk fused",
         f'{len(d["contributions"])} of 7 dimensions scored, coverage '
         f'{d["fused"]["coverage"]:.0%}, risk {d["fused"]["score"]}.'),
        ("decide", "Policy applied",
         f'Band {d["outcome"]["band_outcome"]}, decision {d["outcome"]["outcome"]}.'),
        ("record", "Recorded in the audit chain", "Hash-chained and sealed."),
    ]
    for key, label, detail in stages:
        out.append({"stage": key, "label": label, "detail": detail,
                    "started_at": ts(t), "latency_ms": STAGE_MS[key]})
        t += STAGE_MS[key] / 1000.0
    return out


def make_graph(sid: str, sp: dict, d: dict) -> dict:
    """Evidence graph, capped at 14 nodes (§C9).

    The cap is a legibility constraint, not a technical one: past about fourteen boxes a graph
    stops being read and starts being admired. Layout is left to dagre in the console; this
    only publishes the topology and the labels.
    """
    nodes = [{"id": "intent", "kind": "source", "label": "Request",
              "detail": d["_channel"], "state": "ok"}]
    edges = []

    present_detectors = [("voice", sp["voice_auth"]), ("video", sp["video_auth"]),
                         ("stylometry", sp["stylometry"])]
    abstained_names = {n for n, _ in sp["detector_abstain"]}
    for name, val in present_detectors:
        if val is None and name not in abstained_names:
            continue
        nid = f"det_{name}"
        nodes.append({"id": nid, "kind": "detector", "label": name.capitalize(),
                      "detail": "abstained" if val is None else f"score {val}",
                      "state": "abstain" if val is None else "ok"})
        edges.append({"from": "intent", "to": nid, "label": ""})
        edges.append({"from": nid, "to": "dim_communication_authenticity", "label": ""})

    for dim in P.RISK_WEIGHTS:
        c = next((c for c in d["contributions"] if c["dimension"] == dim), None)
        nodes.append({
            "id": f"dim_{dim}", "kind": "dimension", "label": DIMENSION_LABEL[dim],
            "detail": (f'{c["raw"]} × {c["weight"]:.2f} = {c["points"]:.2f}' if c
                       else "not evaluated"),
            "state": "ok" if c else "abstain",
            "points": c["points"] if c else None,
        })
        edges.append({"from": f"dim_{dim}", "to": "fusion",
                      "label": f'{c["points"]:.2f}' if c else "abstained"})
        if not any(e["to"] == f"dim_{dim}" for e in edges):
            edges.append({"from": "intent", "to": f"dim_{dim}", "label": ""})

    nodes.append({"id": "fusion", "kind": "fusion", "label": "Weighted fusion",
                  "detail": f'risk {d["fused"]["score"]}, coverage '
                            f'{d["fused"]["coverage"]:.0%}', "state": "ok"})
    outcome = d["outcome"]
    nodes.append({"id": "decision", "kind": "decision", "label": outcome["outcome"],
                  "detail": f'band {outcome["band_outcome"]}',
                  "state": outcome["outcome"].lower()})
    edges.append({"from": "fusion", "to": "decision", "label": "band"})

    ctrl = outcome["override_applied"] or outcome["forced_by"]
    if ctrl:
        nodes.append({"id": "control", "kind": "control", "label": ctrl,
                      "detail": "replaces the band" if outcome["override_applied"]
                                else "raises the floor", "state": "block"})
        edges.append({"from": "control", "to": "decision", "label": "overrides"})

    if len(nodes) > 14:
        raise AssertionError(f"{sid}: evidence graph has {len(nodes)} nodes, cap is 14")
    return {"nodes": nodes, "edges": edges}


def intent_confidence_detail(raw: dict, sp: dict, value: int) -> dict:
    parts = {
        "semantic_drift": raw["semantic_drift"],
        "fingerprint": P.FP_PENALTY[sp["fp"]],
        "behavioural": raw["behavioural"],
        "device_channel": raw["device_channel"],
        "beneficiary": raw["beneficiary"],
        "extraction_inverse": 100 - sp["extraction_confidence"],
    }
    rows = []
    for k, w in P.INTENT_PENALTY_WEIGHTS.items():
        v = parts[k]
        used = P.ABSTAIN_INTENT_PENALTY if v is None else v
        rows.append({"factor": k, "weight": w, "value": v, "value_used": used,
                     "abstained": v is None, "points": P.r1(w * used)})
    clamp = None
    if sp["duress"]:
        clamp = ("Clamped to 25. The words were an approval; the circumstances were not, and a "
                 "coerced approval must never present as a confident one.")
    elif sp["fp"] == "MISMATCH":
        clamp = ("Clamped to 25. The approval is cryptographically bound to a transaction that "
                 "is not the one being executed.")
    return {
        "value": value,
        "formula": "100 − Σ(weight × penalty)",
        "penalties": rows,
        "penalty_total": P.r1(sum(r["points"] for r in rows)),
        "clamped_to": 25 if clamp else None,
        "clamp_reason": clamp,
        "excludes": ["voice_authenticity", "video_authenticity"],
        "excludes_reason": ("Deliberately independent of voice and video. A perfect clone must "
                            "not be able to raise confidence in intent."),
    }


# What would have to become true for a forced outcome to lift. A numeric counterfactual is the
# wrong answer here: the score was already inside APPROVE and lowering it further changes nothing.
FORCED_COUNTERFACTUAL = {
    "FC-1": ("No change to risk scoring would approve this. More of the request has to become "
             "measurable before any approval is possible."),
    "FC-2": ("The risk score was already inside the approve band; lowering it further changes "
             "nothing. A scoreable sample of the modality that abstained is what is missing."),
    "FC-3": ("No change to risk scoring would approve this. The request has to be matched "
             "against a captured authorization first."),
    "PC-1": ("No change to risk scoring would approve this. The request has to be matched "
             "against a captured authorization first."),
    "PC-2": ("No change to risk scoring would approve this. More of the request has to become "
             "measurable before any approval is possible."),
    "PC-3": "Out-of-band verification is in progress.",
    "PC-4": ("Nothing about the scoring is in question. Out-of-band confirmation on an "
             "independent channel is required because of the amount, and it would be required "
             "at any risk score."),
    "PC-5": ("No change to risk scoring would approve this. A request that closely repeats an "
             "earlier one has to be confirmed as intended, not scored as routine."),
    "PC-6": ("No change to risk scoring would release this while the breaker is open. Request "
             "volume has to return to normal, or an officer has to close the breaker manually."),
}

# A duress record must not carry a sentence that reads as advice for getting the payment through.
# The requester's screen shows ordinary verification; nothing is lost, because the security desk
# view derives the same counterfactual from `contributions`, which is published in full.
DURESS_COUNTERFACTUAL = ("Out-of-band verification is in progress. No further detail is "
                         "published on this record.")


def make_assessment(sid: str, sc: dict, sp: dict, d: dict, intent: dict, exes: dict) -> dict:
    o, fused = d["outcome"], d["fused"]
    ho = override_block(sid, sp, sc, d["ben"], exes)
    fb = forced_block(o["forced_by"], fused["coverage"], intent["amount_display"],
                      sp["channel_switch_flags"], sp["fp"], sp["replay_similarity"])
    if o["duress_escalation"]:
        cf = {"kind": "withheld", "narrative": DURESS_COUNTERFACTUAL,
              "derivable_from": "contributions"}
    elif ho:
        cf = {"kind": "categorical", "narrative": ho["counterfactual"]}
    elif fb:
        # Includes the open breaker, whose band was CHALLENGE rather than APPROVE: a control that
        # blocks regardless of score must not be answered with "it would have scored lower if…".
        cf = {"kind": "categorical", "narrative": FORCED_COUNTERFACTUAL[fb["code"]]}
    else:
        cf = P.counterfactual_numeric(d["contributions"], fused["score"])
    top = ([ho["reason"]] if ho else []) + ([fb["reason"]] if fb else []) + \
          [c["reason"] for c in d["contributions"][:3]]

    # Which of B's §16.2 steps actually produced the answer. Order matters: duress is step 3 and
    # carries `override_applied: "DURESS"`, so it has to be tested before the hard-override branch
    # or a duress record claims it was decided by an override it never evaluated.
    step = ("breaker" if o["control_label"] else
            "duress" if o["duress_escalation"] else
            "hard_override" if o["override_applied"] else
            fb["step"] if fb else "band")
    if fb:
        # PC-6 is reachable from step 1 as well as step 6 — B keeps it in both places on purpose
        # ("defence in depth is free here"). The record names where it fired, not where it lives.
        fb["step"] = step
    return {
        "assessment_id": f"ASM-{sid}",
        "intent_id": intent["intent_id"],
        "scored_at": ts(1.157),
        "policy_version": POLICY_VERSION,
        "engine_version": ENGINE_VERSION,
        "mode": "FULL",
        "risk_score": fused["score"],
        "band_outcome": o["band_outcome"],
        "decision": o["decision"],
        "outcome": o["outcome"],
        # Which of B's §16.2 steps produced the answer. Published so the console can render the
        # step that decided rather than inferring it from a combination of nulls.
        "decided_at_step": step,
        "override_applied": o["override_applied"],
        "control_label": o["control_label"],
        # Every floor and precondition that failed, not just the one that decided. A floor that
        # fired under an already-CHALLENGE band explains the coverage note without having changed
        # the answer, and conflating the two overstates what the control did.
        "floors_failed": o["floors_failed"],
        "preconditions_failed": o["preconditions_failed"],
        "arithmetic": {
            "contributions_subtotal": fused["subtotal"],
            "coverage": fused["coverage"],
            "renormalized": fused["renormalized"],
            "uncertainty_penalty": fused["uncertainty_penalty"],
            "uncertainty_penalty_rate": P.UNCERTAINTY_PENALTY,
            "risk_score": fused["score"],
            "explanation": (
                f'{fused["subtotal"]:.2f} ÷ {fused["coverage"]:.2f} coverage = '
                f'{fused["renormalized"]:.2f}, plus a '
                f'{fused["uncertainty_penalty"]:.2f}-point uncertainty penalty for what could '
                f'not be measured = {fused["score"]}.'
                if fused["coverage"] < 1.0 else
                f'{fused["subtotal"]:.2f} across all seven dimensions, nothing abstained, '
                f'no uncertainty penalty = {fused["score"]}.'),
        },
        "contributions": d["contributions"],
        "abstentions": d["abstentions"],
        "intent_confidence": intent_confidence_detail(d["raw"], sp, d["intent_confidence"]),
        "hard_override": ho,
        "forced_by": fb,
        "counterfactual": cf,
        "required_actions": REQUIRED_ACTIONS[o["decision"]],
        "top_reasons": top,
        # Never rendered on the requester's screen. The console reads this only in the security
        # desk view; §C12 and the bundle-grep test both enforce that. The requester's client is
        # driven by `visible_to_requester` instead, which is a plain UI state name on every
        # scenario and so distinguishes nothing on its own.
        "duress_escalation": o["duress_escalation"],
        "visible_to_requester": o["visible_to_requester"] or o["decision"],
        "circuit_breaker": {"state": sp["breaker"], "flags": list(sp["channel_switch_flags"])},
        "evidence_graph": make_graph(sid, sp, d),
        "latency_ms": sum(STAGE_MS.values()),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="verify derived values against scenarios.json and disk; write nothing")
    args = ap.parse_args()

    scenarios = {s["id"]: s for s in load("scenarios.json")["scenarios"]}
    bens = {b["beneficiary_id"]: resolve_beneficiary(b)
            for b in load("beneficiaries.json")["beneficiaries"]}
    personas = load("personas.json")
    exes = {e["executive_id"]: e for e in personas.get("executives", [])}

    if set(scenarios) != set(SPEC):
        raise SystemExit(f"scenarios.json and golden_spec.py disagree on ids: "
                         f"{sorted(set(scenarios) ^ set(SPEC))}")

    rows, failures, written = [], [], {}
    for sid in sorted(SPEC):
        sc, sp = scenarios[sid], SPEC[sid]
        d = build(sid, sc, sp, bens, exes)
        intent = make_intent(sid, sc, sp, d["ben"], d["amount_minor"])
        assessment = make_assessment(sid, sc, sp, d, intent, exes)
        decision = assessment["decision"]
        fixture = {
            "_generated_by": "services/audit/tools/make_golden.py — do not hand-edit",
            "_mocked": "Replace with a live response from :8002 at integration.",
            "scenario": {k: sc[k] for k in
                         ("id", "title", "channel", "class", "expected_decision",
                          "expected_frictionless", "hero", "proves", "description")},
            "intent": intent,
            "signals": make_signals(sid, sc, sp, d),
            "assessment": assessment,
            "challenge": make_challenge(sid, sp, intent, d["ben"]),
            "out_of_band": make_oob(sid, intent, exes, sc) if decision == "CHALLENGE" else None,
            "capability_token": make_token(sid, intent, decision),
            "timeline": make_timeline(sid, sp, d),
            "coverage_note": sp["coverage_note"],
        }
        written[sid] = fixture

        want, got = sc["expected_decision"], d["outcome"]["outcome"]
        if got != want:
            failures.append((sid, want, got, d["fused"]["score"]))
        rows.append((sid, sc["class"], d["fused"]["score"],
                     f"{d['fused']['coverage']:.0%}", d["intent_confidence"],
                     d["outcome"]["band_outcome"],
                     d["outcome"]["override_applied"] or d["outcome"]["forced_by"] or "—",
                     got, want, "ok" if got == want else "MISMATCH"))

    w = "{:<5}{:<8}{:>6}{:>7}{:>6}  {:<10}{:<8}{:<19}{:<19}{}"
    print(w.format("id", "class", "score", "cov", "ic", "band", "ctrl",
                   "derived", "expected", ""))
    for r in rows:
        print(w.format(*[str(x) for x in r]))

    if failures:
        print(f"\n{len(failures)} scenario(s) do not match the frozen expectation:")
        for sid, want, got, score in failures:
            print(f"  {sid}: expected {want}, derived {got} (score {score})")
        return 1

    index = {
        "_note": ("Generated. `make_golden.py --check` regenerates everything and diffs; a "
                  "hand-edit will be reported as drift."),
        "policy_version": POLICY_VERSION,
        "engine_version": ENGINE_VERSION,
        "generated_from": ["contracts/scenarios.json", "contracts/personas.json",
                           "contracts/beneficiaries.json",
                           "services/audit/tools/golden_spec.py"],
        "scenarios": [
            {"id": sid, "title": f["scenario"]["title"], "class": f["scenario"]["class"],
             "channel": f["scenario"]["channel"], "hero": f["scenario"]["hero"],
             "decision": f["assessment"]["decision"], "outcome": f["assessment"]["outcome"],
             "risk_score": f["assessment"]["risk_score"],
             "intent_confidence": f["assessment"]["intent_confidence"]["value"],
             "coverage": f["assessment"]["arithmetic"]["coverage"],
             "amount_display": f["intent"]["amount_display"],
             "file": f"{sid}.json"}
            for sid, f in sorted(written.items())],
    }

    drift = []
    OUT.mkdir(parents=True, exist_ok=True)
    for sid, fixture in sorted(written.items()):
        path = OUT / f"{sid}.json"
        text = json.dumps(fixture, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                drift.append(sid)
        else:
            path.write_text(text, encoding="utf-8")
    idx_text = json.dumps(index, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    idx_path = OUT / "index.json"
    if args.check:
        if not idx_path.exists() or idx_path.read_text(encoding="utf-8") != idx_text:
            drift.append("index")
        if drift:
            print(f"\n{len(drift)} file(s) differ from a fresh generation: "
                  f"{', '.join(drift)}\nrun: python3 services/audit/tools/make_golden.py")
            return 1
        print(f"all {len(rows)} scenarios match contracts/scenarios.json; "
              f"contracts/golden/ is up to date")
        return 0
    idx_path.write_text(idx_text, encoding="utf-8")
    print(f"\nwrote {len(written)} fixtures + index.json to contracts/golden/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

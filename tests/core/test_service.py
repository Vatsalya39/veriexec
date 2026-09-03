"""§23 over HTTP: the edge that adds nothing.

Two of these are worth showing. `test_the_edge_adds_nothing_to_the_decision` asserts the JSON
coming back over the wire is byte-identical to what `assess()` returns in process — the
cheapest possible proof that no policy is hiding in the transport layer. And
`test_no_route_can_fail_into_an_approve` is §23's rule that *"a 500 from your service must not
be convertible by a caller into a payment"*, asserted over every way this service knows how
to fail, including an exception nobody predicted.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from packages.core import clock
from packages.core.assess import STUBBED_DIMENSIONS, UNVERIFIED_CLAIMS, assess, preimage_fields
from packages.core.crypto.fingerprint import FINGERPRINT_FIELDS, fingerprint
from packages.core.models import AssessInput, SignalBundle, TransactionIntent
from packages.core.policy.constants import BANDS, REQUIRED_ACTIONS, RISK_WEIGHTS
from packages.core.policy.version import policy_hash, policy_version
from packages.core.scoring.fusion import INTENT_EXCLUDED_SIGNALS
from packages.core.service import app as service

APP_SRC = Path(service.__file__)

#: The instant §10.4's worked example is written at. The service is asked to assess *at* it,
#: which is the only reason a fixture dated in the future works at all.
NOW = clock.iso(clock.parse_iso("2026-09-18T14:02:11+05:30"))

ON_RECORD, SWAPPED = "50100234874471", "50100234879982"

INTENT = dict(
    transaction_id="S06", requester="Ananya Rao", action="TRANSFER", amount="4500000",
    currency="INR", beneficiary="Kalyani Forge Components Pvt Ltd",
    destination_account=SWAPPED, purpose="Q3 vendor settlement", channel="VIDEO",
    extraction_confidence=94,
)

BUNDLE = dict(
    transaction_id="S06", identity_confidence=91, communication_authenticity=96,
    deepfake_voice_score=88.0, social_engineering_score=70,
    social_engineering_indicators=["urgency", "secrecy", "authority"],
)

#: The pre-image as the CFO approved it — paying the account on record.
APPROVED = preimage_fields(
    TransactionIntent(**{**INTENT, "destination_account": ON_RECORD}), executive_id="EXE-001"
)
PRESENTED = fingerprint(APPROVED)


@pytest.fixture()
def client() -> TestClient:
    """`raise_server_exceptions=False` so the catch-all handler is exercised, not bypassed."""
    return TestClient(service.create_app(), raise_server_exceptions=False)


def body(**over) -> dict:
    """One `/v1/assess-risk` request, replaying S06 at the spec's instant."""
    context = {"reference_fields": APPROVED, "now_iso": NOW, "replay": True}
    context.update(over.pop("context", {}))
    return {"intent": INTENT, "signal_bundle": BUNDLE, "presented_fingerprint": PRESENTED,
            "context": context, **over}


#: S09: the binding holds — this is the CFO's own transaction, paying the account on record —
#: and the marker still came through. The refusal has to be invisible, so the money is stopped
#: by the absent capability token rather than by anything the requester can see.
DURESS_BODY = body(intent={**INTENT, "destination_account": ON_RECORD},
                   signal_bundle={**BUNDLE, "duress_flag": True})


def test_healthz_is_the_frozen_shape(client):
    """§13's keys exactly. `make demo` polls this before it opens a browser."""
    r = client.get("/healthz")
    assert r.status_code == 200
    h = r.json()

    assert h["ok"] is True and h["service"] == "core"
    assert h["mode"] in ("live", "cached", "offline")
    assert h["policy_version"] == policy_version()
    assert h["degraded_mode"] is bool(STUBBED_DIMENSIONS or UNVERIFIED_CLAIMS)


def test_both_policy_stamps_ride_every_response(client, monkeypatch):
    """§23 says every response. An error response is the one where it matters most: the
    audit needs to know which rules refused, not only which rules approved."""
    ok = client.get("/healthz")
    bad = client.post("/v1/assess-risk", json={})
    monkeypatch.setattr(service, "assess", _explode)
    boom = client.post("/v1/assess-risk", json=body())

    assert (ok.status_code, bad.status_code, boom.status_code) == (200, 400, 500)
    for r in (ok, bad, boom):
        assert r.headers["X-Policy-Version"] == policy_version()
        assert r.headers["X-Policy-Hash"] == policy_hash()


def _explode(*_a, **_kw):
    raise ZeroDivisionError("a bug nobody predicted")


def test_s06_blocks_over_http(client):
    """The flagship scenario, through the transport C actually calls."""
    a = client.post("/v1/assess-risk", json=body()).json()

    assert a["decision"] == "BLOCK"
    # The band PUBLISHES what the score alone would have said (§16.5: show where the policy
    # overruled its own score), so it moves with the real weights and is never pinned to the
    # stub-era 58. 35.0 now, up from 29.0, because this body carries an approved pre-image:
    # `semantic_drift` measures the swapped account instead of abstaining.
    assert a["band_outcome"] == "CHALLENGE"
    assert a["risk_score"] == 35.0
    assert a["override_applied"] == "HO-1"
    # The uncollapsed policy outcome now survives to C alongside the wire decision (§6.6).
    assert a["outcome"] == "BLOCK"
    assert a["hard_overrides_fired"] == ["FINGERPRINT_MISMATCH"]
    assert a["fingerprint_status"] == "MISMATCH"
    assert a["intent_confidence"] == 25
    assert a["capability_token"] is None
    assert a["required_actions"] == ["contact_executive_out_of_band", "notify_security_officer"]
    assert a["fingerprint_deltas"][0]["field"] == "destination_account"
    assert SWAPPED not in json.dumps(a)          # redacted to a tail, everywhere at once


def test_the_edge_adds_nothing_to_the_decision(client):
    """The whole claim of this module, as one equality.

    Same inputs, same instant, and the wire bytes match what the pure core produced in
    process. There is no policy in the transport layer, because there is no room for any.
    """
    in_process = assess(
        AssessInput(intent=TransactionIntent(**INTENT), signals=SignalBundle(**BUNDLE),
                    presented_fingerprint=PRESENTED),
        reference_fields=APPROVED, now=clock.parse_iso(NOW),
    )
    over_the_wire = client.post("/v1/assess-risk", json=body()).json()

    # `by_alias` matters: `FieldChange.from_` ships as `from` on the wire, and FastAPI
    # serializes by alias — comparing the raw dump would differ on exactly that key.
    assert over_the_wire == json.loads(in_process.model_dump_json(by_alias=True))


def test_either_signal_key_is_accepted_and_they_must_agree(client):
    """A accepts `signal_bundle`, B's own tests say `signals`. Both work; disagreement does not."""
    with_contract_name = client.post("/v1/assess-risk", json=body()).json()
    b = body()
    b["signals"] = b.pop("signal_bundle")
    with_internal_name = client.post("/v1/assess-risk", json=b).json()

    assert with_contract_name == with_internal_name

    conflict = body()
    conflict["signals"] = {**BUNDLE, "identity_confidence": 3}
    r = client.post("/v1/assess-risk", json=conflict)
    assert r.status_code == 400
    assert r.json()["error_code"] == "SCHEMA_VIOLATION"


def test_caller_time_requires_an_admitted_replay(client):
    """Whoever controls `now` controls every validity window, in both directions.

    So the guard is not on the direction — a past instant revives an expired authorization
    just as a future one opens a window that has not opened. The guard is on the claim, which
    B can publish in a header and an auditor can read.
    """
    live = client.post("/v1/assess-risk", json={"intent": INTENT})
    assert live.status_code == 200
    assert live.headers["X-Assessed-At-Source"] == "service"

    replayed = client.post("/v1/assess-risk", json=body())
    assert replayed.headers["X-Assessed-At-Source"] == "caller"
    assert replayed.json()["assessed_at"] == NOW

    unflagged = client.post("/v1/assess-risk",
                            json={"intent": INTENT, "context": {"now_iso": NOW}})
    assert unflagged.status_code == 400
    assert "context.replay" in unflagged.json()["message"]


#: Every way a caller can make this service fail, including the one nobody wrote a branch for.
FAILURES = [
    ("no body at all", "/v1/assess-risk", {}),
    ("intent is not an object", "/v1/assess-risk", {"intent": "TRANSFER 45 lakh"}),
    ("unflagged time travel", "/v1/assess-risk", {"intent": INTENT, "context": {"now_iso": NOW}}),
    ("garbage instant", "/v1/assess-risk",
     {"intent": INTENT, "context": {"now_iso": "yesterday", "replay": True}}),
    ("neither fields nor intent", "/v1/fingerprint", {}),
    ("both fields and intent", "/v1/fingerprint", {"fields": APPROVED, "intent": INTENT}),
    ("a partial pre-image", "/v1/fingerprint", {"fields": {"transaction_id": "S06"}}),
    ("a partial pre-image to verify", "/v1/fingerprint/verify",
     {"presented": "de" * 32, "current_fields": {"transaction_id": "S06"}}),
]


@pytest.mark.parametrize("label,path,payload", FAILURES, ids=[f[0] for f in FAILURES])
def test_no_route_can_fail_into_an_approve(client, label, path, payload):
    """§14's fail-safe direction, and §23's sentence about the 500, as one test.

    Every failure leaves as the frozen three-key body, and `safe_outcome` is CHALLENGE or
    BLOCK. There is no fourth possibility: `IntentLockError` refuses to construct one.
    """
    r = client.post(path, json=payload)
    err = r.json()

    assert r.status_code >= 400
    assert set(err) >= {"error_code", "message", "safe_outcome"}
    assert err["safe_outcome"] in ("CHALLENGE", "BLOCK")
    assert err["safe_outcome"] != "APPROVE"
    assert "decision" not in err                 # an error is not an assessment


def test_an_unhandled_error_is_a_challenge_and_not_a_stack_trace(client, monkeypatch):
    """The traceback goes to the log. What crosses the network is a safe outcome."""
    monkeypatch.setattr(service, "assess", _explode)
    r = client.post("/v1/assess-risk", json=body())
    err = r.json()

    assert r.status_code == 500
    assert err["error_code"] == "INTERNAL"
    assert err["safe_outcome"] == "CHALLENGE"
    text = json.dumps(err)
    for leak in ("ZeroDivision", "Traceback", "nobody predicted", "app.py", "assess.py"):
        assert leak not in text, f"the error body leaks {leak!r}"


def test_the_fingerprint_route_does_the_twelve_field_projection_for_its_callers(client):
    """The route exists so nobody reimplements `preimage_fields()` in another language.

    That reimplementation is how an intermittent `MISMATCH` gets born: one team formats the
    amount as a float, or omits an absent key instead of sending an explicit null, and the
    hash differs on one laptop out of three.
    """
    from_fields = client.post("/v1/fingerprint", json={"fields": APPROVED}).json()
    from_intent = client.post("/v1/fingerprint", json={
        "intent": {**INTENT, "destination_account": ON_RECORD}, "executive_id": "EXE-001",
    }).json()

    assert from_fields["fingerprint"] == PRESENTED == from_intent["fingerprint"]
    assert from_intent["fields"] == APPROVED
    assert tuple(from_intent["fingerprint_fields"]) == FINGERPRINT_FIELDS
    assert from_intent["fields"]["amount_minor_units"] == 450_000_000
    assert '"amount_minor_units":450000000' in from_intent["canonical_form_preview"]


def test_the_verify_route_never_manufactures_a_match(client):
    """UNVERIFIABLE when there is nothing to compare, and a named delta when there is."""
    current = preimage_fields(TransactionIntent(**INTENT), executive_id="EXE-001")

    nothing = client.post("/v1/fingerprint/verify", json={"current_fields": current}).json()
    assert nothing["verdict"] == "UNVERIFIABLE"
    assert nothing["fingerprint_status"] == "NOT_YET_VERIFIED"
    assert nothing["deltas"] == []

    tampered = client.post("/v1/fingerprint/verify", json={
        "presented": PRESENTED, "current_fields": current, "reference_fields": APPROVED,
    }).json()
    assert tampered["verdict"] == "MISMATCH"
    assert tampered["deltas"][0]["field"] == "destination_account"
    assert tampered["deltas"][0]["severity"] == "critical"
    assert ON_RECORD not in json.dumps(tampered) and SWAPPED not in json.dumps(tampered)

    matching = client.post("/v1/fingerprint/verify", json={
        "presented": PRESENTED, "current_fields": APPROVED, "reference_fields": APPROVED,
    }).json()
    assert matching["verdict"] == "MATCH" and matching["deltas"] == []


def test_the_policy_route_publishes_the_live_numbers(client):
    """§23's transparency feature, asserted against the constants rather than a copy.

    If this test ever needs editing because a threshold moved, that is the endpoint doing its
    job: the published document is generated from `policy/constants.py` at call time, so it
    cannot describe a policy the code does not run.
    """
    p = client.get("/v1/policy").json()

    assert p["policy_version"] == policy_version() and p["policy_hash"] == policy_hash()
    assert p["weights"] == dict(RISK_WEIGHTS)
    assert [(b["low"], b["high"], b["outcome"]) for b in p["bands"]] == list(BANDS)
    assert [o["order"] for o in p["overrides"]] == list(range(1, len(p["overrides"]) + 1))
    assert p["overrides"][0] == {"id": "HO-1", "wire_code": "FINGERPRINT_MISMATCH", "order": 1}
    assert p["required_actions"] == list(REQUIRED_ACTIONS)
    assert p["fingerprint_fields"] == list(FINGERPRINT_FIELDS)
    assert p["intent_confidence"]["cap_on_mismatch"] == 25


def test_the_policy_route_admits_what_is_still_stubbed(client):
    """A demo that publishes its own gaps is the one an auditor can believe.

    Both lists are the two frozensets themselves, so a scorer landing updates this endpoint
    by deleting its name in one place — there is no second inventory to forget.
    """
    d = client.get("/v1/policy").json()["degraded"]

    assert d["stubbed_dimensions"] == sorted(STUBBED_DIMENSIONS)
    assert d["unverified_claims"] == sorted(UNVERIFIED_CLAIMS)
    assert d["degraded_mode"] is bool(STUBBED_DIMENSIONS or UNVERIFIED_CLAIMS)
    assert "B2" in d["authorization_store"]          # the caller-supplied-binding limitation
    assert d["missing_policy_artefacts"] == []       # every hashed artefact is on disk


def test_the_policy_route_names_no_media_term_in_its_intent_confidence_section(client):
    """The thesis, published as a document a judge can open in a browser tab.

    The excluded list is the *product*: it is the sentence "we did not let a voice score
    decide whether this payment was authorized", written where an auditor can check it.
    """
    ic = client.get("/v1/policy").json()["intent_confidence"]

    assert ic["excluded_signals"] == list(INTENT_EXCLUDED_SIGNALS)
    assert set(ic["weights"]).isdisjoint(INTENT_EXCLUDED_SIGNALS)
    for term in ("deepfake", "voice", "video", "liveness", "authenticity"):
        assert term not in json.dumps(ic["weights"]), f"an intent weight mentions {term!r}"


def test_no_route_mints_a_capability_token(client):
    """Invariant 9 over HTTP. Minting is B10's, it happens after an APPROVE, and no route
    reachable today is a shortcut to it — including the one that returns an APPROVE."""
    duress = client.post("/v1/assess-risk", json=DURESS_BODY).json()
    blocked = client.post("/v1/assess-risk", json=body()).json()

    assert duress["decision"] == "APPROVE"          # deliberately routine-looking (Invariant 5)
    assert duress["capability_token"] is None       # and it releases nothing
    assert blocked["capability_token"] is None


def test_duress_reaches_the_wire_as_a_routine_approve_with_no_token(client):
    """S09 over HTTP, and the one thing C must not render.

    `duress_escalation`, `override_applied`, `hard_overrides_fired` and the `DURESS` reason
    *code* are structured §6.3/§6.6 fields, so they cross the wire — the security officer's
    console needs them, and C is responsible for keeping them off the requester's screen.
    What B can enforce here is the prose, and this asserts both halves of that split: the
    fact is present in the structure, and absent from every human-readable string.
    """
    a = client.post("/v1/assess-risk", json=DURESS_BODY).json()

    assert a["decision"] == "APPROVE" and a["duress_escalation"] is True
    assert a["capability_token"] is None
    assert a["requires_out_of_band_verification"] is True
    assert a["cooldown_seconds"] > 0
    assert a["override_applied"] == "DURESS"                    # structured: the console reads it
    assert [r["code"] for r in a["reasons_detailed"]] == ["DURESS"]

    prose = " ".join([*a["risk_reasons"], a["degraded_reason"], a["recommended_action"],
                      *a["required_actions"],
                      *(r["text"] for r in a["reasons_detailed"])]).lower()
    for word in ("duress", "coerc", "marker", "phrase", "codeword", "hostage", "safe word"):
        assert word not in prose, f"the wire prose leaks {word!r}"


def test_timings_are_opt_in_so_replay_stays_byte_comparable(client):
    """A measured duration is the one field that cannot be identical on two runs.

    So it is off unless asked for. That is what lets §19.2's replay compare whole response
    bodies byte-for-byte instead of comparing them field-by-field with an exceptions list.
    """
    default = client.post("/v1/assess-risk", json=body()).json()
    timed = client.post("/v1/assess-risk", json=body(context={"include_timings": True})).json()

    assert default["latency_ms"] == {}
    assert timed["latency_ms"]["assess_ms"] >= 0.0
    assert timed["decision"] == default["decision"]              # the timing changed nothing
    assert {k: v for k, v in timed.items() if k != "latency_ms"} \
        == {k: v for k, v in default.items() if k != "latency_ms"}


def test_a_foreign_origin_is_not_granted_cors(client):
    """§13 froze the origin list. A page on another host must not be able to read a decision.

    This is a browser-enforced control, so what is asserted is the header the browser acts on:
    the console's origin is echoed, an attacker's is not reflected back at all.
    """
    allowed = client.options("/v1/assess-risk", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
    })
    foreign = client.options("/v1/assess-risk", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "POST",
    })

    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "https://evil.example" not in foreign.headers.get("access-control-allow-origin", "")
    assert foreign.headers.get("access-control-allow-origin") != "*"


#: `app.py` may legitimately *read* the rule tables in order to publish them at `/v1/policy`.
#: What it may never do is import the `Decision` vocabulary, because the only reason to hold
#: that enum is to compare against a decision or to write one.
ALLOWED_POLICY_IMPORTS = {"APPROVE_PRECONDITIONS", "HARD_OVERRIDES", "constants"}


def test_the_edge_does_not_write_decisions():
    """Invariant 2 as a structural property of this file, not a promise in its docstring.

    A route that patches `decision` after the fact would pass every other test in this module
    — the body would still be schema-valid and the headers would still be stamped. So the
    guard is on the source: no assignment anywhere in `app.py` targets a `.decision`,
    `.band_outcome` or `.risk_score` attribute, and the file does not import the vocabulary
    it would need to invent one.
    """
    tree = ast.parse(APP_SRC.read_text(encoding="utf-8"))

    written = {
        t.attr for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for t in node.targets if isinstance(t, ast.Attribute)
    } | {
        node.target.attr for node in ast.walk(tree)
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Attribute)
    }
    assert written.isdisjoint({"decision", "band_outcome", "risk_score", "capability_token"}), \
        f"the edge assigns policy output: {sorted(written)}"

    imported = {
        alias.name for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("decide")
        for alias in node.names
    }
    assert imported <= ALLOWED_POLICY_IMPORTS, f"the edge imports {sorted(imported)}"
    assert "Decision" not in {
        alias.name for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) for alias in node.names
    }

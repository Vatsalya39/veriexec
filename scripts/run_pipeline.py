"""The whole backend as one uninterrupted run: A -> B -> C's human step -> B -> audit. §16, §23

    python scripts/run_pipeline.py                      # in-process, all 22 samples
    python scripts/run_pipeline.py --live               # over HTTP against A and B
    python scripts/run_pipeline.py --sample S06 -v      # one scenario, with the pre-image diff
    python scripts/run_pipeline.py --audit var/pipeline.ndjson   # + a verifiable chain

Why this file exists: **the flow is two-pass, and nothing in the repo ran both passes.**
`AssessInput`'s own docstring says `authorization` and `verification_channel_id` "are only
present on the second pass, after C has collected a human response, which is when PC-1 and
PC-4 can actually pass" — so a harness that calls `assess()` once is testing a system that
has been asked to authorize a payment nobody has approved yet. It answers CHALLENGE, which is
correct, and it can never answer anything else. Seven of the twenty-two documented outcomes
are unreachable in one pass, and four more need world state that no single request carries.

The passes, and what each one is for:

    pass 1   A's intent + signals, no approval artefact. This is the screen C renders: a risk
             number, a coverage number, and the reasons. PC-1 fails by construction, so the
             honest outcome is CHALLENGE or BLOCK — never APPROVE.
    (C)      A human answers. The console binds the transaction *at signing time*: it mints a
             nonce and a validity window and takes the fingerprint of the exact pre-image the
             executive is looking at.
    pass 2   the same intent, now carrying that `AuthorizationRecord` and the channel the
             answer came back on. Now PC-1 can pass, `semantic_drift` has a second statement
             to compare against, and `device_channel` has a channel to judge.

Two rules keep this from becoming a scoring fixture that flatters itself:

**Nothing is asserted that the data does not say.** The world state comes from
`scripts/world_state.py`, which reads `metadata.prior_events` with A's own extractor. No
sample id appears in any branch here or there. A scenario with no prior events runs with no
reference pre-image, an empty breaker window and a freshly minted approval — and gets
whatever that produces.

**A BLOCK is final.** If pass 1 blocks, there is no pass 2: nobody is invited to approve a
transaction the policy already refused, and a driver that asked anyway would be manufacturing
the human confirmation that Invariant 9 exists to prevent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from packages.core import clock                                        # noqa: E402
from packages.core.models import BreakerState                          # noqa: E402
from scripts import world_state as ws_mod                              # noqa: E402

SAMPLES_DIR = REPO_ROOT / "packages" / "signal_intel" / "samples"

#: Where a fresh console approval's window ends, when no prior grant is being cited. 15
#: minutes is `contracts/`-adjacent policy rather than a fact about a scenario, so it lives
#: here as a named default and is printed in the run header instead of hiding in a call.
FRESH_AUTHORIZATION_TTL_SECONDS = 900

#: The service URLs the `--live` path talks to. Read from the environment under the names
#: `04_INTEGRATION_AND_CONFORMANCE.md` uses, with the loopback defaults every service binds to.
A_URL = os.environ.get("INTENTLOCK_A_URL") or os.environ.get("INTENTLOCK_SIGNAL_URL") \
    or "http://127.0.0.1:8001"
B_URL = os.environ.get("INTENTLOCK_B_URL") or os.environ.get("INTENTLOCK_CORE_URL") \
    or "http://127.0.0.1:8002"
C_URL = os.environ.get("INTENTLOCK_C_URL") or os.environ.get("INTENTLOCK_AUDIT_URL") \
    or "http://127.0.0.1:8003"


# ----------------------------------------------------------------------- the two backends

class Backend:
    """A and B, reachable two ways.

    The in-process backend imports them; `--live` posts to them. Both satisfy the same three
    methods, which is the point: if the HTTP contract has drifted from the function signature,
    running the same corpus through both surfaces says so immediately, and that is precisely
    the class of bug that only shows up at an integration boundary.
    """

    label = "in-process"

    def process(self, request: dict) -> dict:
        from packages.signal_intel.pipeline import process_communication
        return process_communication(request)

    def project(self, intent: dict, *, executive_id: str, nonce: str,
                window: tuple[str, str]) -> tuple[dict, str]:
        """`TransactionIntent` -> `(pre-image, fingerprint)` through B's ONE projection site."""
        from packages.core.assess import preimage_fields
        from packages.core.crypto.fingerprint import fingerprint
        from packages.core.models import TransactionIntent
        fields = preimage_fields(
            TransactionIntent.model_validate(intent), executive_id=executive_id,
            nonce=nonce, window_start=window[0], window_end=window[1],
        )
        return fields, fingerprint(fields)

    def assess(self, payload: dict, *, reference_fields: dict | None,
               breaker_state: BreakerState, now_iso: str) -> dict:
        from packages.core.assess import assess
        from packages.core.models import AssessInput
        result = assess(
            AssessInput.model_validate(payload), reference_fields=reference_fields,
            breaker_state=breaker_state, now=clock.parse_iso(now_iso),
        )
        return result.model_dump(mode="json")


class LiveBackend(Backend):
    """The same three calls over HTTP. §23's wire contract, exercised rather than described."""

    label = "live"

    def __init__(self, a_url: str = A_URL, b_url: str = B_URL, timeout: float = 15.0) -> None:
        import urllib.request                       # stdlib only: this script installs nothing
        self._opener = urllib.request.build_opener()
        self.a_url, self.b_url, self.timeout = a_url.rstrip("/"), b_url.rstrip("/"), timeout

    def _post(self, url: str, body: dict) -> dict:
        import urllib.error
        import urllib.request
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST",
                                     headers={"content-type": "application/json"})
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:400]
            raise RuntimeError(f"POST {url} -> {exc.code}: {detail}") from exc
        except OSError as exc:
            raise RuntimeError(f"POST {url} unreachable: {exc}. Is the service running?") from exc

    def process(self, request: dict) -> dict:
        return self._post(f"{self.a_url}/v1/process-communication", request)

    def project(self, intent: dict, *, executive_id: str, nonce: str,
                window: tuple[str, str]) -> tuple[dict, str]:
        # `/v1/fingerprint` exists so that no other team reimplements the projection; taking
        # `fields` back from it as well as the hash is what makes that guarantee usable.
        out = self._post(f"{self.b_url}/v1/fingerprint", {
            "intent": intent, "executive_id": executive_id, "nonce": nonce,
            "validity_window_start_iso": window[0], "validity_window_end_iso": window[1],
        })
        return out["fields"], out["fingerprint"]

    def assess(self, payload: dict, *, reference_fields: dict | None,
               breaker_state: BreakerState, now_iso: str) -> dict:
        # `replay: true` is not a formality. `_resolve_now` refuses a caller-supplied instant
        # without it, and rightly: whoever controls `now` controls every validity window. A
        # corpus of stored records assessed at their recorded instants *is* a replay.
        return self._post(f"{self.b_url}/v1/assess-risk", {
            **payload,
            "context": {
                "reference_fields": reference_fields,
                "breaker_state": breaker_state.value,
                "now_iso": now_iso, "replay": True,
            },
        })


# ------------------------------------------------------- the approved pre-image, and the past

def _reference_intent(intent: dict, approval: ws_mod.PriorEvent) -> dict:
    """The intent *as the executive approved it*: this transaction, with the earlier values.

    Only fields the prior event actually stated are overridden. That asymmetry is deliberate —
    a difference may only be claimed where the approval really said something different, and
    everything else (transaction id, requester, purpose, channel) is shared because it is the
    same transaction. `deltas()` then reports exactly the fields that changed under the
    executive's feet, which is what HO-1's reason string reads out.

    `action` is skipped when the extractor said `OTHER`: that is its abstention for the verb,
    not a claim that the approval authorized "other", and treating it as a value would invent
    an action drift on every approval written without one (S16).

    `amount_normalization` is dropped rather than inherited. It is the provenance of the
    *current* request's number — "two point five crore -> 25000000.0" — and carrying it onto a
    different amount would leave a fallback path in `minor_units` pointing at the wrong money.
    """
    ex = approval.extracted
    out = {k: v for k, v in intent.items() if k != "amount_normalization"}
    for key in ("amount", "currency", "beneficiary", "destination_account"):
        if ex.get(key) is not None:
            out[key] = ex[key]
    action = str(getattr(ex.get("action"), "value", ex.get("action") or ""))
    if action and action != "OTHER":
        out["action"] = action
    return out


def _seed_breaker(world: ws_mod.WorldState, executive_id: str):
    """A `Breaker` that has already seen this scenario's own history. §15.2

    Each scenario gets its own breaker, not one shared across the corpus: the twenty-two
    samples are independent case files at different instants, and letting S03 trip the breaker
    for S04 would fabricate an organizational fact out of the order a harness happens to
    iterate in.

    Prior requests are observed with `risk_score=0.0`, because they were never assessed and
    inventing a number for them would be exactly the sort of unearned input this codebase
    keeps refusing. They do not need one: `trip_same_beneficiary_count` counts *requests to
    one new payee*, and S12's three chat requests to Global Trading FZE inside nine minutes
    satisfy it on their own. If a scenario's history is thinner than that, the breaker stays
    closed — which is the correct answer rather than a missed detection.
    """
    from packages.core.policy.breaker import Breaker, WindowEvent
    breaker = Breaker()
    for event in world.prior_requests:
        breaker.observe(
            WindowEvent(
                at=event.at, executive_id=executive_id or "",
                risk_score=0.0,
                beneficiary_id=str(event.extracted.get("beneficiary_id") or ""),
            ),
            now=world.now,
        )
    return breaker


# ------------------------------------------------------------------------------ one scenario

@dataclass
class SampleRun:
    """Everything one scenario produced, in the order it happened."""

    sample_id: str
    world: ws_mod.WorldState
    intent: dict = field(default_factory=dict)
    signals: dict = field(default_factory=dict)
    first: dict = field(default_factory=dict)
    second: dict | None = None
    breaker_state: BreakerState = BreakerState.CLOSED
    reference_fields: dict | None = None
    presented_fingerprint: str = ""
    verification_channel: str = ""
    audit: list[dict] = field(default_factory=list)
    error: str = ""

    @property
    def final(self) -> dict:
        """The assessment that decided it — pass 2 when there was one, else pass 1."""
        return self.second or self.first

    @property
    def passes(self) -> int:
        return 2 if self.second else 1


def run_sample(sample: dict, backend: Backend, *,
               ttl_seconds: int = FRESH_AUTHORIZATION_TTL_SECONDS) -> SampleRun:
    """A -> B -> C's human step -> B, for one sample. Returns both passes.

    The only place in the codebase where the flow its own docstrings describe actually runs
    end to end.
    """
    world = ws_mod.read(sample)
    run = SampleRun(sample_id=world.sample_id, world=world)

    # --- A ------------------------------------------------------------------------------
    produced = backend.process({
        "channel": sample["channel"],
        "raw_text_or_transcript": sample["raw_text_or_transcript"],
        "metadata": sample["metadata"],
        "sample_id": world.sample_id,
        "detector_script": sample.get("detector_script") or {},
        "freshness_token": None,
        "freshness_echoed": sample.get("freshness_echoed"),
    })
    run.intent, run.signals = produced["intent"], produced["signals"]
    window = world.authorization_window(ttl_seconds)

    # --- pass 1: the screen C renders. No approval artefact exists yet ------------------
    # The reference pre-image is supplied on this pass too. It cannot produce a MATCH —
    # `verify()` returns UNVERIFIABLE with nothing presented — but `semantic_drift` needs it
    # to have a second statement to compare against, which is the difference between "the
    # request agrees with the approval" and "the request agrees with itself".
    reference_fields = None
    if world.has_reference:
        reference_fields, _ = backend.project(
            _reference_intent(run.intent, world.approval),
            executive_id="", nonce=world.nonce, window=window,
        )
    breaker = _seed_breaker(world, "")
    run.breaker_state = breaker.state(world.now)
    now_iso = clock.iso(world.now)
    run.first = backend.assess(
        {"intent": run.intent, "signals": run.signals, "scenario_id": world.sample_id},
        reference_fields=reference_fields, breaker_state=run.breaker_state, now_iso=now_iso,
    )

    if str(run.first.get("decision")) == "BLOCK":
        # Final. Nobody is asked to approve what policy already refused (Invariant 9), and a
        # driver that asked anyway would be manufacturing the confirmation it then reports.
        run.reference_fields = reference_fields
        return run

    # --- C: a human answers, and the console binds the transaction at signing time -------
    # Now that B has resolved the requester, the reference can be projected against the same
    # executive id as the current pre-image, so a `deltas()` entry can only come from a field
    # the approval really stated differently.
    executive_id = str(run.first.get("executive_id") or "")
    reference_hash = ""
    if world.has_reference:
        reference_fields, reference_hash = backend.project(
            _reference_intent(run.intent, world.approval),
            executive_id=executive_id, nonce=world.nonce, window=window,
        )
    _, current_hash = backend.project(
        run.intent, executive_id=executive_id, nonce=world.nonce, window=window,
    )
    # The approval artefact carries the hash of **what was approved** — the earlier pre-image
    # when one exists, otherwise the request in front of the executive, which is what "bound at
    # signing time" means. One rule, no per-scenario branch: if nothing was altered the two
    # hashes are equal and this is a MATCH; if something was, it is a MISMATCH with deltas,
    # and HO-1 blocks unconditionally. S06 is the second case and needed no special handling.
    presented = reference_hash if world.has_reference else current_hash

    # Which channel the answer came back on. `console` is the honest default — it is what C's
    # dashboard is — except where the case file says otherwise: S13's prior event reads "OOB
    # verification response submitted on the same phone session SES-7781", so the answer
    # arrived on the channel that asked, and B is told exactly that. Note the driver does not
    # set `channel_independent`; it names the channel and lets B's own `verdict()` judge it,
    # because "nothing a caller asserts about itself is believed" (assess.py's second rule).
    origin_channel = str(run.intent.get("channel") or "")
    origin_device = str(((run.signals.get("device_info") or {}).get("device_id")) or "")
    if world.verification_on_origin:
        verification_channel, verification_device = origin_channel, origin_device
    else:
        verification_channel, verification_device = "console", ""
    run.verification_channel = verification_channel

    authorization = {
        "transaction_id": run.intent.get("transaction_id") or world.sample_id,
        "executive_id": executive_id,
        "transaction_fingerprint": presented,
        # The frozen §6.4 vocabulary, not free text. An out-of-band approval is what C's
        # console collects, and `EXPIRED` below is a *result*, not a window: the window itself
        # travels in `issued_at`/`expires_at` so B decides whether it has closed.
        "verification_method": "OOB_APPROVAL",
        "verification_result": "APPROVED",
        "nonce": world.nonce,
        "issued_at": window[0],
        "expires_at": window[1],
        "origin_channel": origin_channel,
        "verification_channel": verification_channel,
    }

    # --- pass 2: the same request, now bound --------------------------------------------
    run.second = backend.assess(
        {"intent": run.intent, "signals": run.signals, "scenario_id": world.sample_id,
         "authorization": authorization, "presented_fingerprint": presented,
         "verification_channel": verification_channel,
         "verification_device_id": verification_device},
        reference_fields=reference_fields, breaker_state=run.breaker_state, now_iso=now_iso,
    )
    run.reference_fields = reference_fields
    run.presented_fingerprint = presented
    return run


# ------------------------------------------------------------------------------- the audit log

#: Which of the frozen §4.2 event types each stage emits. Nothing here invents a name; adding
#: one is a G0 decision, and `db.append` rejects anything outside the vocabulary anyway.
def _abstained(assessment: dict) -> list[str]:
    """Which dimensions had nothing to measure. Read off the table, not from a summary field.

    There is no `abstained_dimensions` on `RiskAssessment` — the abstentions are rows in
    `contribution_table` with a reason attached, which is the stronger arrangement: an
    abstention that appears in a list without its reason is exactly the "number with no
    reason" §10.3 forbids.
    """
    return [str(row.get("factor")) for row in (assessment.get("contribution_table") or [])
            if row.get("abstained")]


def _audit_events(run: SampleRun) -> list[tuple[str, str, dict]]:
    """`(event_type, actor, payload)` for one scenario, in the order the stages ran.

    Payloads carry decisions and hashes, never evidence: no transcript, no audio, no frames,
    no untokenized PII. `db._reject_media` enforces that at the service and is applied here too,
    so the offline chain a judge verifies has been through the same gate as the live one.
    """
    intent, first, final = run.intent, run.first, run.final
    txn = str(intent.get("transaction_id") or run.sample_id)
    events: list[tuple[str, str, dict]] = [
        ("COMMUNICATION_RECEIVED", "signal_intel", {
            "sample_id": run.sample_id, "channel": intent.get("channel"),
            "received_at": clock.iso(run.world.now),
            "prior_events_seen": len(run.world.events),
        }),
        ("INTENT_CAPTURED", "signal_intel", {
            "transaction_id": txn, "action": intent.get("action"),
            "amount_minor_units": first.get("amount_minor_units"),
            "currency": intent.get("currency"),
            "beneficiary": intent.get("beneficiary"),
            "extraction_mode": intent.get("extraction_mode"),
            "extraction_confidence": intent.get("extraction_confidence"),
        }),
        ("RISK_ASSESSED", "core", {
            "pass": 1, "risk_score": first.get("risk_score"),
            "coverage": first.get("coverage"), "decision": first.get("decision"),
            "band_outcome": first.get("band_outcome"),
            "fingerprint_status": first.get("fingerprint_status"),
            "abstained": _abstained(first),
        }),
    ]
    if run.breaker_state is not BreakerState.CLOSED:
        events.append(("BREAKER_TRIPPED", "core", {
            "state": run.breaker_state.value,
            "window_events": len(run.world.prior_requests),
            "reason": "prior requests inside the rolling window; see policy/breaker.py",
        }))
    return events + _audit_second_pass(run, txn)


def _audit_second_pass(run: SampleRun, txn: str) -> list[tuple[str, str, dict]]:
    """C's human step, pass 2, and the final decision — or nothing, if pass 1 blocked."""
    final = run.final
    if run.second is None:
        return [("DECISION_RENDERED", "core", {
            "transaction_id": txn, "decision": final.get("decision"),
            "passes": 1, "override_applied": final.get("override_applied"),
            "hard_overrides_fired": final.get("hard_overrides_fired"),
            "required_actions": final.get("required_actions"),
            "note": "blocked on the first pass; no approval was solicited",
        })]

    events: list[tuple[str, str, dict]] = [
        ("CHALLENGE_ISSUED", "console", {
            "transaction_id": txn, "reason": run.first.get("recommended_action"),
            "required_actions": run.first.get("required_actions"),
        }),
        ("FINGERPRINT_COMPUTED", "console", {
            "transaction_id": txn,
            # The hash, never the pre-image. `canonical_form_preview` contains the destination
            # account in clear and `/v1/fingerprint`'s docstring says it "must never be logged".
            "transaction_fingerprint": run.presented_fingerprint,
            "bound_at_signing_time": True,
            "validity_window": {"start_iso": run.world.authorization_window()[0],
                                "end_iso": run.world.authorization_window()[1]},
            "reference_pre_image_held": run.reference_fields is not None,
        }),
        ("CHALLENGE_ANSWERED", "console", {
            "transaction_id": txn, "verification_channel": run.verification_channel,
            "verification_method": "OOB_APPROVAL",
            # B's verdict, not the console's claim about itself.
            "channel_independence": run.second.get("channel_independence"),
        }),
        ("RISK_ASSESSED", "core", {
            "pass": 2, "risk_score": run.second.get("risk_score"),
            "coverage": run.second.get("coverage"),
            "decision": run.second.get("decision"),
            "band_outcome": run.second.get("band_outcome"),
            "fingerprint_status": run.second.get("fingerprint_status"),
            "fingerprint_deltas": run.second.get("fingerprint_deltas"),
            "abstained": _abstained(run.second),
        }),
    ]
    if final.get("duress_escalation"):
        # Invariant 5. The event exists so the security view can act; the payload names no
        # marker, no scheme and no position, and the requester's screen shows an APPROVE.
        events.append(("DURESS_ESCALATED", "core", {
            "transaction_id": txn, "outcome": final.get("outcome"),
            "visible_decision": final.get("decision"),
            "note": "silent escalation; the requester sees no indication",
        }))
    events.append(("DECISION_RENDERED", "core", {
        "transaction_id": txn, "decision": final.get("decision"),
        "passes": 2, "outcome": final.get("outcome"),
        "override_applied": final.get("override_applied"),
        "hard_overrides_fired": final.get("hard_overrides_fired"),
        "required_actions": final.get("required_actions"),
    }))
    return events


class ChainWriter:
    """Links the pipeline's events into the same hash chain `verify_chain.py` checks. §4.3

    Deliberately *not* a second implementation: `chain.link` and `db`'s payload guards are
    imported from the audit service, so an NDJSON file written here and a chain written by the
    live service are verifiable by the same offline walker with no flag to say which produced it.

    `record_id` is derived rather than drawn from `uuid4`. The service is free to use a random
    id — its records are appended once — but a driver whose whole purpose includes proving
    byte-identical replay (Invariant 8) cannot emit a different chain for the same corpus twice.
    """

    def __init__(self) -> None:
        sys.path.insert(0, str(REPO_ROOT / "services" / "audit"))
        from app import chain, db                      # type: ignore[import-not-found]
        self._chain, self._db = chain, db
        self.records: list[dict] = []
        self._prev = db.GENESIS_PREV_HASH

    def append(self, event_type: str, actor: str, payload: dict, *,
               transaction_id: str, timestamp: str) -> dict:
        if event_type not in self._chain.EVENT_TYPES:
            raise ValueError(f"{event_type!r} is outside the frozen §4.2 vocabulary")
        self._db._reject_media(payload)               # the same gate the service applies
        payload = self._db._decimalize(payload)       # floats -> fixed decimals before hashing
        seq = len(self.records) + 1
        record = {
            "seq": seq,
            "record_id": hashlib.sha256(
                f"{transaction_id}|{seq}|{event_type}".encode("utf-8")).hexdigest()[:32],
            "timestamp": timestamp, "event_type": event_type,
            "transaction_id": transaction_id, "actor": actor, "payload": payload,
            "policy_version": _policy_version(),
            "policy_hash": _policy_hash(),
        }
        linked = self._chain.link(record, self._prev)
        self._prev = linked["record_hash"]
        self.records.append(linked)
        return linked

    def verify(self) -> dict:
        return self._chain.verify(self.records)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for record in self.records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _policy_hash() -> str:
    """B's own hash over the policy artefacts, so a record says which policy decided it."""
    from packages.core.policy.version import policy_hash
    return policy_hash()


def _policy_version() -> str:
    """B's version, not the audit service's constant. The record names the policy that decided,
    and only B holds that; `db.POLICY_VERSION` is C's default for records B did not produce."""
    from packages.core.policy.version import policy_version
    return policy_version()


# ------------------------------------------------------------------------------ the whole corpus

def load_samples(only: list[str] | None = None) -> list[dict]:
    paths = sorted(SAMPLES_DIR.glob("S*.json"))
    if only:
        wanted = {s.strip().upper() for s in only}
        paths = [p for p in paths if p.stem.upper() in wanted]
        missing = wanted - {p.stem.upper() for p in paths}
        if missing:
            raise SystemExit(f"no such sample(s): {', '.join(sorted(missing))}")
    return [json.loads(p.read_text(encoding="utf-8")) for p in paths]


#: `Outcome.wire()` collapses two policy outcomes into the frozen three decisions, so a sample
#: whose `expected_decision` is an Outcome name is compared after the same collapse.
COLLAPSE = {"SILENT_ESCALATION": "APPROVE", "BREAKER_TRIPPED": "BLOCK"}


def _matches_expectation(sample: dict, final: dict) -> tuple[bool, bool]:
    """`(decision_ok, override_ok)` against the sample's own two expectation fields.

    The sample files, not `contracts/scenarios.json`, are the expectation of record here:
    `expected_decision` + `expected_override` is the only pair that can express S09 ("looks
    like APPROVE, emits SILENT_ESCALATION"), whereas `scenarios.json` has no override column
    and puts the Outcome name in the Decision field, which is not a valid Decision value.
    """
    want_decision = str(sample.get("expected_decision") or "")
    want_override = sample.get("expected_override")
    got_decision = str(final.get("decision") or "")
    decision_ok = got_decision == COLLAPSE.get(want_decision, want_decision)
    if not want_override:
        return decision_ok, True
    got = set(final.get("hard_overrides_fired") or ())
    got |= {str(final.get("outcome") or ""), str(final.get("override_applied") or "")}
    return decision_ok, want_override in (got - {""})


def run_corpus(samples: list[dict], backend: Backend, *,
               chain_writer: ChainWriter | None = None) -> list[SampleRun]:
    """Every sample, start to finish. One scenario's failure does not stop the corpus."""
    runs: list[SampleRun] = []
    for sample in samples:
        try:
            run = run_sample(sample, backend)
        except Exception as exc:                      # noqa: BLE001 - reported, not swallowed
            run = SampleRun(sample_id=str(sample.get("sample_id") or "?"),
                            world=ws_mod.read(sample), error=f"{type(exc).__name__}: {exc}")
        if chain_writer is not None and not run.error:
            txn = str(run.intent.get("transaction_id") or run.sample_id)
            stamp = clock.iso(run.world.now)
            for event_type, actor, payload in _audit_events(run):
                run.audit.append(chain_writer.append(
                    event_type, actor, payload, transaction_id=txn, timestamp=stamp))
        runs.append(run)
    return runs


def _print_table(runs: list[SampleRun], samples: list[dict]) -> int:
    by_id = {str(s.get("sample_id")): s for s in samples}
    hits = 0
    print(f"{'id':<5}{'expected':<30}{'got':<30}{'':<5}detail")
    for run in runs:
        if run.error:
            print(f"{run.sample_id:<5}{'':<30}{'ERROR':<30}{'':<5}{run.error[:80]}")
            continue
        sample = by_id.get(run.sample_id, {})
        final = run.final
        decision_ok, override_ok = _matches_expectation(sample, final)
        ok = decision_ok and override_ok
        hits += ok
        want = str(sample.get("expected_decision") or "?")
        if sample.get("expected_override"):
            want += f"+{sample['expected_override']}"
        fired = list(final.get("hard_overrides_fired") or ())
        got = str(final.get("outcome") or final.get("decision") or "")
        if fired:
            got += "+" + ",".join(fired)
        print(f"{run.sample_id:<5}{want:<30}{got:<30}{'OK ' if ok else 'MISS':<5}"
              f"p{run.passes} risk={float(final.get('risk_score') or 0):>5.1f} "
              f"cov={float(final.get('coverage') or 0):.2f} "
              f"band={final.get('band_outcome')} fp={final.get('fingerprint_status')} "
              f"chan={(final.get('channel_independence') or {}).get('code', '?')} "
              f"brk={run.breaker_state.value}")
    return hits


def _print_detail(run: SampleRun) -> None:
    """The pre-image diff and both passes, for `-v`. What a reviewer actually needs to see."""
    world = run.world
    print(f"\n--- {run.sample_id} ------------------------------------------------------")
    print(f"  now                 {clock.iso(world.now)}")
    print(f"  prior events        {len(world.events)} "
          f"({', '.join(e.kind for e in world.events) or 'none'})")
    if world.authorization_id:
        print(f"  cited authorization {world.authorization_id} "
              f"{world.issued_at} -> {world.expires_at} "
              f"{'EXPIRED' if world.authorization_expired else 'open'}")
    if run.reference_fields:
        current = {k: v for k, v in (run.reference_fields or {}).items()}
        print("  approved pre-image  " + json.dumps(
            {k: current[k] for k in ("amount_minor_units", "destination_account",
                                     "beneficiary_id_or_name") if k in current}))
    for label, assessment in (("pass 1", run.first), ("pass 2", run.second)):
        if not assessment:
            continue
        print(f"  {label}              {assessment.get('decision')} "
              f"risk={assessment.get('risk_score')} coverage={assessment.get('coverage')} "
              f"fp={assessment.get('fingerprint_status')}")
        for delta in assessment.get("fingerprint_deltas") or []:
            print(f"     delta {delta.get('field')}: {delta.get('expected')} -> "
                  f"{delta.get('presented')} [{delta.get('severity')}]")
        for reason in (assessment.get("risk_reasons") or [])[:3]:
            print(f"     - {reason}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the INTENTLOCK backend end to end: A -> B -> C's step -> B -> audit.")
    parser.add_argument("--live", action="store_true",
                        help=f"POST to A ({A_URL}) and B ({B_URL}) instead of importing them")
    parser.add_argument("--sample", action="append", metavar="ID",
                        help="only these samples (repeatable), e.g. --sample S06")
    parser.add_argument("--audit", metavar="PATH", nargs="?", const="var/pipeline.ndjson",
                        help="write the hash-linked audit chain as NDJSON "
                             "(verify it with scripts/verify_chain.py)")
    parser.add_argument("--json", metavar="PATH",
                        help="write the full per-sample assessments as JSON")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="print the pre-image diff and reasons for each sample")
    args = parser.parse_args(argv)

    backend: Backend = LiveBackend() if args.live else Backend()
    samples = load_samples(args.sample)
    writer = ChainWriter() if args.audit else None

    print(f"INTENTLOCK pipeline | {backend.label} | {len(samples)} sample(s) | "
          f"policy {_policy_version()} {_policy_hash()[:12]} | "
          f"fresh authorization TTL {FRESH_AUTHORIZATION_TTL_SECONDS}s")
    runs = run_corpus(samples, backend, chain_writer=writer)
    hits = _print_table(runs, samples)
    if args.verbose:
        for run in runs:
            if not run.error:
                _print_detail(run)
    errors = [r for r in runs if r.error]
    print(f"\n{hits}/{len(runs)} match the sample's expected (decision, override)"
          + (f"; {len(errors)} raised" if errors else ""))

    if writer is not None:
        path = REPO_ROOT / args.audit if not os.path.isabs(args.audit) else Path(args.audit)
        writer.write(path)
        verdict = writer.verify()
        state = "OK" if verdict.get("valid") else f"BROKEN at seq {verdict.get('broken_at')}"
        print(f"audit chain: {len(writer.records)} records -> {path} | {state}")
        if not verdict.get("valid"):
            return 1

    if args.json:
        path = REPO_ROOT / args.json if not os.path.isabs(args.json) else Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([{
            "sample_id": r.sample_id, "passes": r.passes, "error": r.error,
            "breaker_state": r.breaker_state.value,
            "reference_fields": r.reference_fields,
            "presented_fingerprint": r.presented_fingerprint,
            "verification_channel": r.verification_channel,
            "first_pass": r.first, "second_pass": r.second,
        } for r in runs], indent=2, sort_keys=True), encoding="utf-8")
        print(f"assessments: {path}")

    # A scenario that raised is a broken pipeline; a scenario that merely missed its expected
    # decision is a calibration result, and the caller reads the table for that.
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

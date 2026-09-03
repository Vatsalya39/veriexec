# CHANGES

Cross-team deviations from the four frozen briefs, and anything that has to be re-agreed at
integration. One entry per decision. Nothing in here is a unilateral change to another team's
contract — where C had to pick something, the entry says what B or A needs to confirm.

Owner: Team C. Entries touching B's policy need B's initials before G1.

---

## C-1 · Precondition ids follow Team B §16.4, not C's earlier draft

**What.** `services/audit/tools/policy_mirror.py` originally invented its own `PC-1..PC-5`
(breaker / coverage / amount ceiling / unscoreable modality / unverified fingerprint). Team B's
brief §16.4 already freezes six ids with different meanings:

| Id | B's predicate (§16.4) |
|---|---|
| `PC-1` | `fingerprint is MATCH` |
| `PC-2` | `coverage >= 0.55` |
| `PC-3` | `not duress_suspected` |
| `PC-4` | `channel_independent` **or** `amount <= ₹50,000` |
| `PC-5` | `replay_risk < 40` |
| `PC-6` | `breaker_state is CLOSED` |

**Why it mattered.** C's `PC-1` meant "velocity breaker open"; B's `PC-1` means "fingerprint was
never bound". At integration B would have emitted `PC-1` and the console would have rendered a
breaker message for a fingerprint failure. The fixtures exist to catch exactly this, so the
fixtures had to stop being the thing that caused it.

**Resolution.** The mirror now uses B's ids and B's predicates verbatim. Fixture effects:
`S02`/`S20` moved from C's `PC-3` to B's `PC-4`, and `S12` from C's `PC-1` to B's `PC-6`. No
expected decision in `contracts/scenarios.json` changed.

**Needs from B.** Nothing, unless §16.4 is still in flux — in which case the mirror is stale and
the fixtures are regenerated, never the other way round.

---

## C-2 · `FC-*` ids assigned to B's unlabelled §16.2 step 5

**What.** B's decision function applies abstention and coverage floors at step 5, *before* the
band is trusted and independently of the step-6 preconditions, but gives them no ids:

```python
# 5. FORCED CHALLENGE — abstention/coverage floors (Invariant 6)
if a.coverage < MIN_COVERAGE or a.fingerprint is FingerprintVerdict.UNVERIFIABLE:
    outcome = max_severity(outcome, "CHALLENGE")
```

C assigned `FC-1` (coverage below floor), `FC-2` (a modality that was present and could not be
scored), `FC-3` (fingerprint not verified) so the console has a stable reason key and a record can
say which floor fired.

**Why `FC-2` exists at all.** B's step-5 condition does not cover it. Team C §6.6 and Invariant 3
require it: a 3.1-second, 4 dB clip is a modality that was *present and unscoreable*, which is not
the same as absent. `S15` is the fixture that depends on it — coverage 75%, fingerprint MATCH,
risk 20, squarely inside APPROVE, and still challenged. Without `FC-2` that scenario approves and
the invariant is decorative.

**Needs from B.** Either adopt `FC-1..FC-3` or publish ids of B's own; C renames, and does not
re-decide, whichever way it goes. If B declines `FC-2` as a floor, say so explicitly — it changes
`S15`'s outcome and that has to be a deliberate call, not a merge artefact.

---

## C-3 · Absent modality vs unscoreable modality

**What.** `modality_unscoreable` in `golden_spec.py` is true only when a detector received input
and could not score it. A text channel having no audio is *absent*, not unscoreable.

**Why.** If absence tripped the floor, every email would be challenged and the control would be
noise. `S05`/`S10`/`S11`/`S14`/`S18` are the absent case and correctly do not trip it; `S15` is the
unscoreable case and does.

---

## C-4 · Team C §17.2 benchmark denominators disagree with the shared context

**What.** `00_SHARED_CONTEXT.md` fixes the scenario set at **14 ATTACK / 8 LEGIT**. Team C §17.2
quotes 11/11. The fixtures and `services/audit/bench.py` follow the shared context.

**Why.** The shared context is the cross-team contract and `contracts/scenarios.json` matches it.
A benchmark whose denominator disagrees with the fixture set reports a wrong rate with confidence.

**Needs from C's own brief.** §17.2 is stale; recorded here and in `docs/BENCH_NOTES.md` rather
than silently reconciled.

---

## C-5 · `S06` intent confidence derives to 12, not the brief's illustrative 20

**What.** Team B's brief uses 20 as an illustrative intent-confidence value for `S06`. Under B's
published `INTENT_PENALTY_WEIGHTS` with `S06`'s dimensions it derives to 12, then clamps to ≤25 for
the fingerprint MISMATCH.

**Why not tuned to 20.** `S06`'s whole point is risk **58** — mid-CHALLENGE — overridden to BLOCK
by `HO-1`. Preserving 58 fixes the dimensions, and the dimensions fix the confidence. Reaching 20
would have required moving a dimension and losing the 58. The clamp reason is published either
way, so nothing in the demo narrative depends on the exact number.

---

## C-6 · Breaker outcome is `BLOCK`, labelled `BREAKER_TRIPPED`

**What.** B's step 1 returns `Decision("BREAKER_TRIPPED", override="BREAKER")`.
`contracts/scenarios.json` expects `BLOCK` for `S12`. The fixture publishes
`decision: "BLOCK"`, `override_applied: "BREAKER"`, `control_label: "BREAKER_TRIPPED"`.

**Needs from B.** Confirm `BREAKER_TRIPPED` is a label on a BLOCK and not a fourth decision value.
If it is a fourth value, `RiskAssessment.decision`'s enum has to say so and the console's band
rendering changes.

---

## C-7 · No unmasked account number in `contracts/golden/`

**What.** Fixtures publish `fingerprint_covered_fields` with account values masked to last-4, plus
`fingerprint_field_order`. `fingerprint_hex` is computed over the **unmasked** values.

**Why.** The fingerprint is only meaningful over the real account, but the published fixture set is
checked into git and rendered in a browser. Tests that need to recompute a digest read the
unmasked values from `contracts/beneficiaries.json`.

---

## C-8 · `sha256_b` in `CANONICAL_JSON_VECTORS.json` is deliberately null

Every digest there was produced by C's implementation only. B fills the `sha256_b` column from an
independent run at G0. Copying C's digest across defeats the entire purpose of the file.

---

## C-9 · No fixed signature vector in `CRYPTO_WIRE_FORMAT.md`

WebCrypto does not expose RFC-6979 deterministic ECDSA, so `r‖s` differs per signature and a fixed
base64url string is not assertable. The frozen vector asserts what actually catches format drift:
32 signed bytes, 64-byte raw signature, 86-character base64url, and a successful cross-language
verify. An earlier draft promised a fixed string; that promise was wrong.

---

## C-10 · Audit payloads carry non-integer quantities as fixed-decimal strings

**What.** Before hashing, `services/audit/app/db.py` converts every `float` in a record payload to
its exact fixed-decimal string form: `0.15` is stored as `"0.15"`, `19.8` as `"19.8"`. Reads convert
back (`chat.py::_num`), so the representation is invisible above the storage layer.

**Why.** Rule 6 of the canonical form is *"money is integer minor units; a float anywhere raises,
never coerces"*, and that rule is correct — a fingerprint computed over a float fails to verify on a
different CPU. But a risk assessment is not a fingerprint. `weight: 0.15`, `points: 19.8` and
`coverage: 0.75` are real fractional quantities and B publishes them as JSON numbers, so
`canonical(payload)` would have raised `NonCanonicalValue` on **every** `RISK_ASSESSED` append. The
audit log could not have stored B's output at all.

**Why not widen `canonical.py`.** That file is a copy of `packages/core/crypto/canonical.py`, and
`contracts/CANONICAL_JSON_VECTORS.json` exists precisely to catch the two copies disagreeing.
Relaxing rule 6 on C's side would have made the vector file assert agreement that no longer held —
turning the one artefact designed to catch integration drift into the thing hiding it. C's copy is
byte-identical to B's and stays that way.

**Where the boundary is.** The fingerprint field set (`s06_fingerprint_fields` in the vector file)
is all integers and strings by design and never touches this path. Only the **audit envelope** —
which C owns — carries the converted form. Fixed-decimal strings are exact, byte-identical in every
language, and hash-stable, which is the property that mattered.

**Needs from B.** Nothing. `RiskAssessment` on the wire is unchanged; this is C's storage form.
Worth knowing at integration: a record read back from the chain returns `"0.15"` where the wire had
`0.15`, and the hash covers the string.

---

## C-11 · §10's count line (14 ATTACK / 8 LEGIT) contradicts its own table (15 / 7)

**What.** `00_SHARED_CONTEXT.md` §10 freezes the scenario table and then summarizes it as
"14 ATTACK, 8 LEGIT". The table itself classifies 15 rows ATTACK (`S03`–`S14`, `S16`–`S18` —
`S17` expects `CHALLENGE` + mandatory OOB) and 7 rows LEGIT. `contracts/scenarios.json`, the
frozen file every team consumes, matches the table.

**Resolution.** The benchmark and tests follow the frozen file: denominators 15 / 7 / 3.
The §12 *outcome* definitions are unchanged. Two §12 judgement calls C had to make:

* **S17 (privileged-action attack, expectation CHALLENGE)** counts as *contained*, and the
  attack-block numerator reports `blocked + contained` so the raw fraction is still visible:
  `14+1/15`. A challenged attacker did not get through; hiding them would understate, and
  counting them as straight BLOCK would overstate.
* **Legit success** follows §12's own sentence — "reach a final APPROVE … or after a
  successful OOB verification" — so an expected-CHALLENGE that was challenged is on the
  approval path (`7/7`), not a failure. The false-challenge metric (denominator 3) is
  where unjustified friction is counted.

**Needs from anyone.** Nothing, unless §10's count line is amended — in which case the
amendment is a contract change through `04_...md` §4, and the fixtures follow the file.

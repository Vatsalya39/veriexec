# INTENTLOCK — Part 4: Integration & Conformance Protocol
## The document that decides whether three parallel builds become one product

> **Audience:** all three agents, plus the human running the clock.
> Read this at `T+0` alongside `00_SHARED_CONTEXT.md`, then again at `G1`, `G2` and `G5`.
> Nothing in this file is optional and nothing in it is a matter of taste.

---

## 1. The one thing this document exists to prevent

Three agents working in parallel for 24 hours will produce three systems that each work alone. The
default outcome — the one that happens unless it is actively prevented — is discovering at `T+18` that
Team A emits `amount` in rupees, Team B expects paise, and Team C formats whatever it gets. Nobody is
wrong. Everybody has to change. There are six hours left and the demo has never run end to end.

So the protocol has one governing rule:

> **Integrate before you implement.** Fake responses on real ports at `T+1:30`, a real vertical slice
> at `T+4:30`, and after that integration is a continuous non-event rather than a phase.

Everything below is machinery for that sentence.

---

## 2. Ownership map — the boundary is a directory, not a conversation

| Path | Owner | Anyone else may |
|---|---|---|
| `packages/signal/` | **A** | read for reference, never edit |
| `packages/core/` | **B** | read for reference, never edit |
| `apps/console/`, `services/audit/`, `packages/bench/` | **C** | read for reference, never edit |
| `contracts/` | **shared, frozen at G0** | change only by the amendment procedure in §4 |
| `tests/conformance/` | **shared** | anyone may add a test; nobody may weaken one |
| `Makefile`, `docker-compose.yml`, `.env.example`, `scripts/` | **shared** | append-only; never restructure another team's target |
| `docs/OWNERSHIP.md` | **shared** | append your files as you create them |

**Rules that keep this honest:**

1. **No cross-package imports.** `packages/core` may not `import signal`. Services talk over HTTP,
   full stop. This is what makes the three lanes genuinely independent — and it is also why a
   contract change is expensive, which is the point.
2. **No shared mutable state.** Three SQLite files (`var/signal.db`, `var/core.db`, `var/audit.db`),
   never one. Two processes writing one SQLite file is a `database is locked` at hour 19.
3. **Duplicated logic is allowed; divergent logic is not.** B and C both canonicalize JSON. They do
   not import each other's implementation — they share `contracts/CANONICAL_JSON_VECTORS.json` and
   both prove they match it. Copy the algorithm, share the test vectors.
4. **`docs/OWNERSHIP.md` is appended to as you go**, not reconstructed at the end. Two agents creating
   `apps/console/src/lib/format.ts` and `packages/core/format.py` with different money rules is a bug
   that ownership discipline catches early and code review at hour 20 does not.

---

## 3. G0 — the freeze, and why 45 minutes of typing saves six hours

`T+0 → T+0:45`. **No agent writes feature code during G0.** All three write `contracts/`.

### 3.1 The G0 checklist

- [ ] `contracts/schemas/*.json` — JSON Schema for `IntentRecord`, `SignalBundle`, `RiskAssessment`,
      `AuditRecord`, `CapabilityToken`. `additionalProperties: false` on every object. Required
      arrays explicit.
- [ ] `contracts/personas.json` — the persona registry, including `known_numbers` and behavioural
      baselines. Duress markers appear **only** as HMAC digests.
- [ ] `contracts/beneficiaries.json` — the beneficiary master including `BEN-004`
      *Meridian Steel & Logistics Pvt Ltd* and its registered accounts.
- [ ] `contracts/scenarios.json` — `S01`–`S22` with `expected_decision` and a one-line description.
- [ ] `contracts/golden/S01..S22.json` — **all 22 fixtures hand-written**, each a complete
      `{intent, signals, context, expected_decision}`.
- [ ] `contracts/CRYPTO_WIRE_FORMAT.md` — B and C agree signature encoding, public-key encoding, the
      exact signed bytes, and one frozen test vector (§6).
- [ ] `contracts/CANONICAL_JSON_VECTORS.json` — at least eight `{input_dict, canonical_string,
      sha256}` triples covering non-ASCII, nested nulls, key order, integer amounts, empty arrays.
- [ ] `.env.example` with every key present and every value empty.
- [ ] `docs/OWNERSHIP.md` created with the four top-level rows from §2.

### 3.2 The fixture rule that makes the fixtures useful

Every golden fixture must be **complete enough to run without the other two services**. A fixture that
only contains a transcript is useless to B; a fixture that only contains scores is useless to A.

```jsonc
// contracts/golden/S06.json  — shape, not content
{
  "scenario_id": "S06",
  "description": "Deepfake video call; account changed after authorization",
  "expected_decision": "BLOCK",
  "expected_override": "HO-1",
  "intent": { "...": "a complete IntentRecord as A would emit it" },
  "signals": { "...": "a complete SignalBundle as A would emit it" },
  "context": { "...": "executive baseline, beneficiary, channel, time" },
  "notes": "risk_score lands in the CHALLENGE band; HO-1 overrides. Deliberate. Do not tune."
}
```

Three consequences worth stating plainly, because each one removes a class of failure:

- **A develops against `intent`/`signals` as a target**, and their extractor's job is to reproduce the
  fixture from the raw transcript. The fixture is the spec.
- **B develops against `intent`/`signals` as input** and never waits for A.
- **C renders `expected_*`** and never waits for B.

Hand-writing 22 fixtures is tedious and it is the highest-leverage 45 minutes in the build.

### 3.3 Amount representation — settle it here or pay for it later

**Every monetary value in every contract, every payload, every database column and every log line is
an integer number of paise, in a field whose name ends `_minor_units`.** There is no field named
`amount` anywhere in the system. Formatting to `₹4,50,000.00` happens exactly once, in
`apps/console/src/lib/money.ts`, at render time.

A `float` holding rupees is not a style preference; it is a rounding bug that will silently change a
fingerprint and make your integrity demo fail for a reason nobody can find at 4 a.m.

---

## 4. Changing a frozen contract — the amendment procedure

Contracts will need to change. The cost of an *unannounced* change is an hour of three-way debugging;
the cost of an announced one is five minutes.

**The procedure, in full:**

1. **Additive-only by default.** A new optional field with a documented default breaks nobody. Prefer
   it to every other option, including the one that is cleaner.
2. **A rename or a type change requires all three teams to acknowledge** before either side ships it,
   and it must be paired with an entry in `docs/CHANGES.md`:
   ```
   2026-09-03T14:22+05:30 | B | SignalBundle.voice_authenticity: int -> int|null
   Reason: abstention must be representable (Invariant 3). Consumers: C (two-number card).
   Acknowledged: A ✓ C ✓ | Fixtures updated: yes | Conformance re-run: green
   ```
3. **Fixtures are updated in the same change.** A contract change that leaves the 22 fixtures invalid
   has broken all three teams simultaneously, which is the exact failure mode the freeze exists to
   prevent.
4. **After `G5` there are no contract changes.** None. If something is wrong after `G5`, it gets
   handled in the narration, not in the schema.

**Deletion is the dangerous one.** Removing a field looks safe when your own tests pass. Grep the
whole repo for the field name before deleting it, including `apps/console/` — TypeScript will not warn
you about a field that arrives at runtime from a Python service.

---

## 5. G1 — the stub contract

`T+1:30`. Every service answers on its real port with a schema-valid **fake** response. This is the
gate that converts integration from an event into a background condition.

| Service | Must answer | With |
|---|---|---|
| A `:8001` | `POST /v1/process-communication`, `POST /v1/extract`, `POST /v1/analyze-signals`, `GET /v1/samples`, `GET /healthz` | the `S06` fixture's `intent` and `signals`, hard-coded |
| B `:8002` | `POST /v1/assess-risk`, `GET /v1/policy`, `GET /healthz` | the `S06` fixture's expected `RiskAssessment`, hard-coded |
| C `:8003` | `POST /v1/audit/append`, `GET /v1/audit/head`, `GET /v1/audit/verify`, `GET /healthz` | a **real** chain — C's is genuine at G1, not stubbed |

**The stub rules:**

- A stub returns a response that **validates against the schema**. A stub returning `{"todo": true}`
  is worse than no stub, because it lets the consumer build against a shape that will never exist.
- A stub is replaced in place. Same URL, same schema, real logic behind it. No `/v2/`, no
  `?real=true`, no second endpoint. Consumers must never know the moment it became real.
- **`GET /healthz` is real from G1**, on all three, returning the frozen shape
  `{ok, service, version, mode, policy_version}`. `make demo` polls all three before opening the
  browser, so a service that starts but is unhealthy fails loudly at launch rather than mid-demo.
- Every stub logs `STUB` at WARN on every call. At `G3` you grep the logs for `STUB`; anything still
  printing it is unfinished work that nobody has noticed.

---

## 6. The two cross-team interfaces that actually break

Everything else is JSON over HTTP. These two are different in kind, they involve two languages, and
each has a failure mode that costs hours and produces a misleading error message.

### 6.1 Canonical JSON — B's fingerprint and C's hash chain must agree

Both compute SHA-256 over a canonical serialization. If they disagree, nothing visibly breaks — you
just get two different hashes for the same content, discovered when someone compares them on stage.

**The frozen rules, identical in both implementations:**

| Rule | Value |
|---|---|
| Key order | lexicographic by Unicode code point (`sort_keys=True`) |
| Separators | `(",", ":")` — no whitespace anywhere |
| Non-ASCII | emitted as-is, **`ensure_ascii=False`** |
| Unicode form | **NFC**, normalized before serialization |
| Nulls | explicit `null`, never omitted |
| Numbers | integers only; no floats in any hashed structure |
| Booleans | JSON `true`/`false` |
| Encoding | UTF-8, no BOM |

`contracts/CANONICAL_JSON_VECTORS.json` is the arbiter. Both B and C run
`test_canonical_json` against it. Neither implementation is authoritative — **the vectors are**, which
is what makes this resolvable without a conversation at 3 a.m.

Include at least one vector containing `"Meridian Steel & Logistics Pvt Ltd"`, one containing a
Devanagari string, and one containing `{"a": null, "b": {"c": null}}`. Those three catch `ensure_ascii`,
NFC and null-omission respectively — the three ways this actually goes wrong.

### 6.2 ECDSA signatures — the browser signs, Python verifies

Frozen in `contracts/CRYPTO_WIRE_FORMAT.md` at G0, signed off by both B and C:

| Item | Value |
|---|---|
| Curve / hash | P-256 (`prime256v1`) / SHA-256 |
| Signed bytes | **the 32 raw bytes of the fingerprint digest** — not the 64-char hex string, not JSON |
| Signature on the wire | **base64url of the 64-byte raw `r‖s` pair, no padding** |
| Public key on the wire | base64url of **SPKI DER**, no padding |
| Conversion | **B** converts raw `r‖s` → DER via `encode_dss_signature`; **C** never converts |
| Frozen vector | one `{private_key_pem, fingerprint_hex, expected_signature_b64u}` triple in the contract file |

The two failure modes, both of which produce the message "signature invalid" and neither of which is a
key problem:

- **Signing the hex string.** Produces a mathematically valid signature over the wrong message.
- **Converting to DER in the browser.** B re-wraps a DER blob as if it were raw `r‖s`.

`tests/conformance/test_signature_crosslang.py` signs the frozen vector in Node and verifies it in
Python, asserting the exact base64url string. **Write this test at G1**, before either side has a UI.
It is fifteen minutes at G1 and two hours at G14.

---

## 7. The event contract — who writes what to the audit log

C owns the log. A and B are its clients. The vocabulary is frozen at G0 and C rejects an unknown
`event_type` with `422` rather than accepting it silently, because a typo'd event code produces a log
that looks complete and is not.

| Event | Written by | At |
|---|---|---|
| `COMMUNICATION_RECEIVED`, `INTENT_CAPTURED` | A | on extraction |
| `FINGERPRINT_COMPUTED`, `RISK_ASSESSED`, `DECISION_RENDERED` | B | on assessment |
| `CHALLENGE_ISSUED`, `CHALLENGE_ANSWERED` | B | including **wrong** answers |
| `SIGNATURE_VERIFIED` | B | valid **and** invalid outcomes |
| `TOKEN_MINTED`, `TOKEN_REDEEMED`, `TOKEN_REDEMPTION_FAILED` | B | every redemption attempt |
| `COOLDOWN_STARTED`, `COOLDOWN_CANCELLED` | B | |
| `BREAKER_TRIPPED`, `BREAKER_CLOSED` | B | |
| `DURESS_ESCALATED` | B | **category only** — no marker, no scheme, no position |
| `CANARY_INJECTED`, `CANARY_RESULT` | C | hourly |
| `POLICY_REPLAYED`, `MODE_CHANGED` | B | |
| `OFFICER_OVERRIDE` | B | with `officer_id` and justification |
| `CHAIN_VERIFIED` | C | on every verify call |
| `OOB_REVEALED`, `OOB_CONTRADICTED` | C | out-of-band verification (field names only) |

**Three rules with no exceptions.** Log every failure, not only successes — a fraud investigator's
first question is *"show me the attempt that failed."* Never write raw audio, video, frames or base64
blobs to the log. Never write PII: account numbers are tokenized (`[ACCOUNT_9f3c1a02]`) before the
append call, by the caller, not by C.

**Append is best-effort from the caller's perspective and must never block a decision.** If `:8003` is
down, B logs locally, sets `audit_degraded: true` on the response, and continues. A system that
refuses to decide because its logger is unavailable has converted an availability problem into a
correctness problem — and C renders that flag as a visible banner so the gap is disclosed rather than
hidden.

---

## 8. `tests/conformance/` — nine tests, one per invariant, shared by all three

This directory is the project's spine and its best answer to *"how do I know your AI is not the weak
link?"* Every team runs `make conformance` before every push. A red conformance run is a build failure,
not a discussion.

| Test | Invariant | Asserts |
|---|---|---|
| `test_no_single_signal_approves.py` | 1 | For each of the 7 dimensions, a bundle where only that dimension is favourable and all others abstain never yields `APPROVE`. Also: `APPROVE` requires ≥3 independent families present. |
| `test_llm_never_decides.py` | 2 | Run all 22 fixtures with an **adversarial LLM stub** that returns `{"decision": "APPROVE", "risk_score": 0}` in every field it can reach. All 22 decisions unchanged. Plus an AST guard: `decide.py` never reads an LLM-sourced attribute name. |
| `test_unavailable_is_not_clean.py` | 3 | For every dimension, `null` scores strictly higher risk than a favourable value, coverage drops, and the uncertainty penalty is applied. `null` never equals `0` in effect. |
| `test_fingerprint_mismatch_blocks.py` | 4 | `MISMATCH` ⇒ `BLOCK` at risk 0 and at risk 99. `UNVERIFIABLE` ⇒ never `APPROVE`. |
| `test_duress_is_silent.py` | 5 | `duress_flag` ⇒ `duress_escalation`, requester-facing payload identical to a normal challenge, and no marker/scheme/position string anywhere in the response or the audit record. |
| `test_channel_independence.py` | 6 | Verification on the origin channel **family** is rejected with `SAME_CHANNEL_VERIFICATION`, not merely penalised. A different device on the same family is still rejected. |
| `test_every_number_has_reasons.py` | 7 | Every contribution above the materiality threshold has ≥1 reason string and a resolvable `evidence_ref`. Empty reasons fail schema validation. |
| `test_decision_reproducible.py` | 8 | Replay every fixture twice under the recorded `policy_version` ⇒ byte-identical `RiskAssessment` (excluding timestamps, which are excluded by name in one place, listed in the test). |
| `test_no_standing_authority.py` | 9 | Token single-use (second redemption fails), scope-limited (different account/amount/device all fail), expiring, and never minted on a non-`APPROVE` decision. |

**Two meta-tests in the same directory**, because they catch the failures that the nine cannot:

- `test_fixtures_valid.py` — all 22 fixtures validate against the schemas and declare an
  `expected_decision`. Run it first; a broken fixture makes every other failure a mystery.
- `test_all_22_decisions.py` — the full matrix, expected vs actual, printed as a table on failure so
  one command tells you which scenarios regressed rather than that "something" did.

**Nobody may weaken a conformance test to make a build green.** If a test is wrong, fix the test in a
change that says so in `docs/CHANGES.md` and gets acknowledged by the other two teams. This is the one
rule most likely to be broken at hour 20 under pressure, which is why it is stated as bluntly as
possible: a green build bought by deleting an assertion is the worst possible trade at that hour,
because the assertion is the product.

---

## 9. The `Makefile` — shared, and the whole build's user interface

Six targets, each of which must work on a clean clone with no `.env` and no network.

| Target | Does | Owner |
|---|---|---|
| `make demo` | starts all three services, polls `/healthz` on each, opens `:5173` | shared |
| `make test` | every team's unit tests, Python + Vitest, non-zero exit on either | shared |
| `make conformance` | `tests/conformance/` — the nine plus the two meta-tests | shared |
| `make bench` | the 22-fixture harness; writes `docs/RESULTS.md` and `var/bench_latest.json` | C |
| `make demo-reset` | fresh audit chain with seeded history, breaker CLOSED, nonces unspent, mode FULL, in under 5 s | C |
| `make freeze` | runs all 22 in `live` mode, caches LLM responses to `contracts/golden/llm/`, switches to `offline` | shared |

`make demo` must never be the first thing anyone runs at `G6`. Run it at `G1` and then continuously.
Each team adds its own sub-target (`make test-signal`, `make test-core`, `make test-console`) and
**never edits another team's target** — the top-level target composes them.

---

## 10. Integration checkpoints — the three-way handshake

Four synchronization points. Each is a fixed, short, scripted exchange rather than an open discussion,
because open discussions at hour 12 cost forty minutes.

### 10.1 `G1` handshake — "does my JSON satisfy you?"

Each team posts to the other two's real endpoints with its real payload and confirms schema validation.
Ten minutes. The output is a line in `docs/CHANGES.md` if anything moved, and silence if nothing did.

### 10.2 `G2` handshake — the S06 vertical slice

One command runs `S06` from transcript to rendered decision to audit record.
`scripts/slice_s06.sh` does A → B → C → console in sequence and prints each hop's status. When it goes
green, **screenshot it**. That is your first fallback asset and the first moment the project provably
exists.

### 10.3 `G3` handshake — the full matrix

`make conformance && make bench` on one machine, in one run, with all three teams' latest `main`. Read
the 22-row table together. Assign every mismatch to exactly one team, in writing, with a deadline
before `G4`. An unassigned mismatch is an unfixed mismatch.

### 10.4 `G5` handshake — freeze and cache

Freeze means the schemas, the weights, the policy, the copy and the fixtures stop moving. Run
`make freeze`, then run all 22 twice in `offline` mode and diff the two runs; a non-empty diff at `G5`
is a determinism bug and it is the last chance to catch one. Then capture the eleven fallback
screenshots and the screen recording — while the system works, not while it is failing.

---

## 11. Merge and branch discipline

- **`main` is always demo-able.** If `main` cannot run `make demo`, that is the only thing anyone works
  on until it can.
- **Three long-lived branches** (`team/a`, `team/b`, `team/c`), rebased onto `main` at each gate, and
  **merged at each gate** rather than at the end. Six merges of 200 lines each is an afternoon of
  nothing; one merge of 1,200 lines is an evening of everything.
- **`contracts/` changes go directly to `main`** in their own commit, announced, never bundled with
  feature work. A contract change buried in a 40-file feature commit is invisible to the other two
  teams — and it is precisely the change they most needed to see.
- **Commit message format:** `[A|B|C|shared] <what changed> (<gate>)`. At hour 20, `git log --oneline`
  filtered by team is how you find out when something broke.
- **Never force-push a shared branch.** Never `git reset --hard` on `main`. If history is wrong, add a
  commit that fixes it; a destructive rewrite at hour 19 with three agents pulling is unrecoverable in
  the time available.
- **Secrets never enter git.** `.env` is gitignored from the first commit, `.env.example` carries empty
  values, `dev/keys/` is gitignored, and no agent commits a file it has not looked at.

---

## 12. Degradation matrix — what still works when something is dead

The judges will ask *"what happens when X fails?"* This table is the answer, and every row is
test-enforced rather than aspirational.

| Dead component | Mode | What still works | What is lost |
|---|---|---|---|
| LLM (no key, no network, timeout) | `NO_LLM` | **Every decision, byte-identical.** All 22 fixtures correct. | Prose explanations → templated fallback; the audit chatbot; unusual-phrasing extraction. |
| Team A's detectors | `NO_DETECTORS` | Deterministic extraction, fingerprinting, policy, all overrides. `S06` still `BLOCK`. | Stylometry, deepfake scores, pressure analysis. Coverage drops, uncertainty penalty applies, more transactions land in `CHALLENGE` — **which is the correct direction**. |
| Both | `MINIMAL` | Fingerprint verification, hard overrides, tokens, the chain. `S06` still `BLOCK`. | Everything advisory. |
| Service A (`:8001`) down | — | B and C serve the golden fixtures with a visible **"cached fixture"** badge. | Live extraction. |
| Service B (`:8002`) down | — | Console renders cached assessments with the same badge; the audit chain is intact. | New decisions — and the console says so rather than approving anything. |
| Service C (`:8003`) down | — | A and B keep deciding; B sets `audit_degraded: true`. | The log and the console. Decisions are queued locally and appended on recovery. |
| SQLite locked / corrupt | — | Services start, report `chain_ok: false`, and refuse to append. | Never a silent overwrite. A broken chain is displayed, never repaired. |

**The direction is invariant across every row: degradation adds friction, never approval.** Write it
down, test it, and say it in exactly those words when asked.

---

## 13. The pre-demo checklist — run this at `G6`, out loud, together

Fifteen minutes, read aloud, one person ticking. Every line has cost somebody a demo somewhere.

**Environment**

- [ ] Laptop on mains power, battery ≥80%, sleep and screensaver disabled.
- [ ] Notifications off — OS, Slack, mail, calendar, phone on silent and face down.
- [ ] Display mirrored at the projector's native resolution; the two big numbers readable from the back.
- [ ] Browser zoom at the level you rehearsed. Bookmarks bar hidden. One window, tabs pre-opened in
      demo order. No devtools open except where the script calls for it (§12 of Team C's prompt).
- [ ] **Network cable unplugged and wifi off**, then `make demo` — proving the offline claim to
      yourselves before you claim it to anyone else.

**System**

- [ ] `make demo-reset` run. Fresh chain with seeded history, breaker CLOSED, nonces unspent,
      mode `FULL`, `INTENTLOCK_MODE=offline`.
- [ ] All three `/healthz` green; `chain_ok: true`; head hash visible in the console footer.
- [ ] `make conformance` green — nine of nine — and the output left on screen in a spare terminal.
      Being able to alt-tab to a green conformance run is worth more than any slide about rigour.
- [ ] `make bench` numbers match `docs/RESULTS.md` and the benchmark screen.
- [ ] `INTENTLOCK_DEMO_ENDPOINTS=1` set **only** in the demo shell, and everyone knows the tamper
      route is deliberate and disclosed.

**People**

- [ ] Every one of the eleven beats assigned to a named person in `docs/DEMO_SCRIPT.md`.
- [ ] Every hostile question in `05_PITCH_AND_JUDGING.md` assigned to a named person.
- [ ] One person owns the clock and signals at 5:00 and 6:30.
- [ ] The fallback screenshots and the 90-second recording are open in a background window, numbered
      to match the beats.
- [ ] Everyone can state the thesis in one sentence, unprompted, in the same words:
      **"Deepfakes attack identity. INTENTLOCK authorizes intent."**

---

## 14. The five ways this project fails, ranked by likelihood

Read this at `T+0` and again at `T+12`. Every item is a failure of coordination, not of engineering —
which is exactly why a technically strong team walks into them.

1. **Late integration.** Three working systems, one broken product, discovered at `T+18`. Prevented by
   `G1` stubs and the `G2` slice, and by nothing else. If you are behind, protect these two gates
   before you protect any feature.
2. **Contract drift.** A field renamed without announcement. The other two teams debug their own
   correct code for an hour. Prevented by additive-only changes and `docs/CHANGES.md`.
3. **Feature sprawl past `G4`.** Every hour spent on a P2 item after `G4` is an hour not spent
   rehearsing, and an unrehearsed demo of a better system loses to a rehearsed demo of a simpler one.
   The cut order exists — `N28`, `N6`, `N22`, the graph half of `N5`, `N26` — and it exists to be used
   without a meeting.
4. **A demo that depends on the venue.** Network, CDN, remote model, cloud API. Offline-first is a
   design constraint from `T+0`, not a hardening step at `G6`.
5. **Claiming more than the code does.** One unsupported sentence on stage — *"we detect deepfakes with
   99% accuracy"* — and a judge who probes it takes the credibility of everything else with it. The
   project's whole rhetorical position is that it does **not** need to detect deepfakes. Do not trade
   that away for a bigger number.

---

## 15. What "integrated" means, precisely

You are integrated when all of the following are true simultaneously, verified in one sitting:

1. `make demo` on a clean clone, no `.env`, no network, brings up three services and the console in
   under two minutes.
2. `make conformance` is green: nine invariants, nine tests, plus the two meta-tests.
3. All 22 scenarios produce their expected decision, in `offline` mode, twice in a row, byte-identically.
4. `S06` runs transcript → extraction → assessment → console → audit record, with the chain verifying
   afterwards, in one unbroken click path.
5. The kill switch flips `NO_LLM` server-side and exactly one field of the response changes.
6. `make bench` prints the five metrics and they match what the benchmark screen displays.
7. The four hero scenarios (`S06`, `S09`, `S15`, `S04`) can be clicked in any order without a reload.
8. Nothing on screen claims a capability the code does not have.

Anything less than all eight is a system that has three owners and no product.

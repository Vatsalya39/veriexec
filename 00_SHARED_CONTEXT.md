# INTENTLOCK — Part 0: Shared Project Context (FROZEN)

> **Paste this entire file into every agent session before the team-specific prompt.**
> Nothing in this file may be changed by any single team. Changes require the
> contract-change protocol in `04_INTEGRATION_AND_CONFORMANCE.md` §4.
>
> Hackathon: Microsoft Innovation Club, VIT Chennai — Cybersecurity track.
> Problem statement: *Deepfake-Resistant Executive Transaction Authorization*.
> Build window: **under 24 hours**. Executors: **one AI coding agent per workstream**.

---

## 1. Project identity

**Name:** INTENTLOCK
**Tagline:** *Deepfakes attack identity. INTENTLOCK authorizes intent.*

**One-paragraph elevator pitch (memorise this; it is the pitch):**

> Every enterprise control in this space asks *"is this really the CFO?"* — and every
> generative model is getting better at making the answer "yes." INTENTLOCK asks a
> different question that no deepfake can answer: *"did the real executive knowingly
> approve **this exact** payee, amount, account and deadline?"* We cryptographically
> bind an authorization to the specific transaction, deliver the confirmation over a
> channel the attacker does not control, require the executive to prove they
> *understood* the transaction rather than merely consented to it, and mint a
> single-use, scope-limited capability instead of a standing approval. The result is a
> control that keeps working **even when the deepfake detector is wrong, even when the
> executive's account is genuinely compromised, and even when our own AI is offline.**

**The thesis sentence for the judges (say this verbatim):**

> A deepfake can steal a face and a voice. It cannot produce a signed, single-use
> authorization bound to an exact payee and amount — because that authorization never
> travels through the channel the attacker controls.

---

## 2. The problem, as issued by the organizers

Finance teams, executive assistants, help desks, banks and payment operations receive
urgent instructions via phone, video, email and chat. Generative voice/video and account
compromise let attackers impersonate executives convincingly. Traditional controls
authenticate a **device, account or channel** — but never prove that the real executive
*originated* the request **and** *approved the exact transaction* (amount, payee, account,
deadline). This is the gap between **communication identity** and **transaction intent**.

Deepfake detection alone is insufficient: it can be evaded by new generators, it degrades
on noisy telephone audio and short utterances, and a **genuine** voice or account can still
be replayed, misused or coerced. The system must be **risk-based, not a universal blocker**,
and **explainable, not a black box**.

Organizer-named success metrics (we will report all five, with numbers — see §12):
attack-block rate, legitimate-approval success, false-challenge rate, verification time,
prevented fraudulent value.

### Central principle

> **Identity authentication is not transaction intent authorization.**
> Ask "did the real executive knowingly approve THIS EXACT transaction?" — not "is this
> really them?"

### Three decision outcomes

| Outcome | Colour | Meaning |
|---|---|---|
| `APPROVE` | green | Proceed. Risk low **and** no hard override fired **and** amount below the no-OOB ceiling. |
| `CHALLENGE` | yellow | Proceed **only** after out-of-band, transaction-bound verification succeeds. |
| `BLOCK` | red | Do not execute. Route to security operations with evidence. |

Two non-obvious states sit alongside these and must not be collapsed into them:
`SILENT_ESCALATION` (duress — looks like APPROVE to the actor, alerts security) and
`BREAKER_TRIPPED` (org-level velocity control — blocks a class of requests, not one request).

---

## 3. The Nine Invariants (test-enforced, non-negotiable)

These are the spine of the project. `tests/conformance/` contains **one named test per
invariant** and all three teams run it. An invariant failure is a build failure. If a judge
asks "what stops your own AI from being the weak link?", the answer is this list.

1. **No single signal can approve.** No individual signal (voice biometrics, deepfake score,
   account auth, MFA, stylometry) may alone produce `APPROVE`. Approval requires fusion of
   at least three independent signal families.
2. **The LLM never decides.** LLMs may extract, classify, summarise, explain and recommend.
   The `decision` field is written **only** by deterministic policy code. There must be no
   code path in which model text can set `decision`.
3. **Unavailable ≠ clean.** A detector that abstains (short utterance, low SNR, unknown
   codec, missing modality) contributes **zero authenticity evidence**. Missing evidence may
   never be scored as favourable evidence.
4. **Fingerprint mismatch is fatal.** `fingerprint_status == "MISMATCH"` ⇒ `BLOCK`,
   unconditionally, regardless of `risk_score`. Enforced in code, not via weights.
5. **Duress is silent.** `duress_flag == true` ⇒ `duress_escalation == true`, a
   normal-looking flow for the actor, and a separate alert to the security view. Never a
   visible "duress detected" banner.
6. **Verification must change channel.** A verification response arriving on the same
   channel, session or device as the originating request is **rejected**, not merely
   penalised.
7. **Every number carries reasons.** Any score above a materiality threshold must emit at
   least one human-readable reason. A populated score with an empty reasons array fails
   schema validation.
8. **Every decision is reproducible.** Replaying a stored audit record under its recorded
   `policy_version` must yield a byte-identical `RiskAssessment`.
9. **No standing authority.** A successful authorization mints a **single-use,
   scope-limited capability token** (exact account, amount ceiling, expiry, one redemption),
   never a general "the CFO approved something" flag.

---

## 4. Workstreams and ownership boundaries

You are building **exactly one** of these. Do not build the others. Do not edit another
team's directory. Design your outputs to plug into theirs via the frozen contracts in §6.

| Team | Name | Role in one line | Owns |
|---|---|---|---|
| **A** | Signal Intelligence & Extraction | The **senses** — raw communication → structured intent + trust signals | `packages/signal/` |
| **B** | Risk Fusion, Fingerprint & Authorization Core | The **brain** — deterministic, explainable, cryptographic decision engine | `packages/core/` |
| **C** | Verification, Dashboard, Audit & Demo | The **face and the proof** — everything a human touches, plus the evidence | `apps/console/`, `services/audit/` |

**Shared, owned by nobody alone (all three must approve a change):** `contracts/`,
`contracts/golden/`, `tests/conformance/`, `Makefile`, `docker-compose.yml`, `.env.example`,
`docs/`.

Dependency direction is strictly one-way: `A → B → C`. Nothing in A may import from B or C.
Nothing in B may import from C. C may read A's endpoints for display context only, never for
decisions. This is why the three streams can be built in parallel with zero coordination
after hour 1.

---

## 5. Non-negotiable design rules (all teams)

1. **LLMs advise; deterministic code decides.** See Invariant 2. Every safety-critical
   numeric must be reproducible without a network call.
2. **Fusion, never a single signal.** See Invariant 1.
3. **Reasons ship with every score.** See Invariant 7. Order reasons by contribution size,
   descending. Plain English, under 90 characters each, no jargon, no raw field names.
4. **Mocks are labelled mocks.** All financial data, executive devices, payment gateways,
   voice/video models and behavioural history are simulated. Every mock carries
   `# MOCKED — replace with real inference in production` at its definition site, and the
   demo narration says so out loud once. Judges punish hidden mocking and reward honest
   mocking.
5. **Build to the contracts in §6 exactly.** Field names and types are frozen. Extensions
   are **additive only** with defaults (§6.6). If you must deviate, you have failed
   integration — use the protocol in `04_...md` §4 instead.
6. **Two-minute cold start.** A judge must go from `git clone` to a running demo with one
   command (`make demo`) in under two minutes, with **no API key required**.
7. **Offline-first, live-optional.** Every LLM call has a deterministic fallback and a
   cached golden response. `INTENTLOCK_MODE=offline` must produce a complete, correct demo
   with the network unplugged. This is not a safety net — it is a **scored feature** we
   demonstrate on purpose (see `05_PITCH_AND_JUDGING.md` §5, "kill the AI" moment).
8. **Transcript content is untrusted input.** Communication text may contain prompt
   injection aimed at our own extractor. Treat it like a SQL parameter, never like an
   instruction. Team A §7 owns the defence; Team B independently recomputes.
9. **No secrets in the repo.** All keys via `.env`, `.env.example` committed with empty
   values, `.env` in `.gitignore`. A committed key is an instant credibility loss in a
   cybersecurity track.
10. **No raw biometric retention.** Never persist raw audio/video in the audit log; persist
    only detector reports and hashes. Say this on the privacy slide.
11. **Determinism where it matters.** Seed every RNG (`INTENTLOCK_SEED=1337`). Two runs of
    the same scenario must produce identical output, or Invariant 8 fails.
12. **Time is explicit.** All timestamps are ISO-8601 with offset, generated from a single
    injectable clock (`now()` helper), never `datetime.now()` scattered inline — otherwise
    expiry tests are flaky and the demo breaks at midnight.
13. **Everything is IST / INR by default.** `Asia/Kolkata`, `INR`, Indian digit grouping and
    lakh/crore parsing (§9). This is a correctness requirement, not a cosmetic one.
14. **Ship the tests.** Each team's Definition of Done is a passing test file, not a
    screenshot. Judges in this track do ask to see tests.

---

## 6. Shared JSON contracts — v1.1 (FROZEN BASE + ADDITIVE EXTENSIONS)

All four base shapes below are **byte-frozen from the original team brief**. Do not rename,
retype or remove a base field. §6.6 defines the additive extensions that carry the novel
work; every extension field has a mandatory default so an older consumer never breaks.

### 6.1 `TransactionIntent` — produced by A, consumed by B

```json
{
  "transaction_id": "string (uuid)",
  "requester": "string (claimed executive name/role)",
  "action": "TRANSFER | CREDENTIAL_RESET | BENEFICIARY_CHANGE | PAYMENT_LIMIT_CHANGE | OTHER",
  "amount": "number | null",
  "currency": "string | null",
  "beneficiary": "string | null",
  "destination_account": "string | null",
  "purpose": "string | null",
  "deadline": "string | null (ISO datetime or free text)",
  "urgency": "LOW | MEDIUM | HIGH",
  "secrecy_flags": ["array of strings, e.g. 'do not tell anyone', 'confidential'"],
  "channel": "PHONE | VIDEO | EMAIL | CHAT | COLLAB_PLATFORM",
  "raw_transcript_or_text": "string",
  "timestamp": "ISO datetime"
}
```

### 6.2 `SignalBundle` — produced by A, consumed by B

```json
{
  "transaction_id": "string (uuid, matches TransactionIntent)",
  "identity_confidence": "number 0-100",
  "communication_authenticity": "number 0-100",
  "deepfake_voice_score": "number 0-100 | null",
  "deepfake_video_score": "number 0-100 | null",
  "stylometry_match_score": "number 0-100 | null (text channels only)",
  "social_engineering_score": "number 0-100",
  "social_engineering_indicators": ["array of strings"],
  "duress_flag": "boolean",
  "duress_reason": "string | null",
  "channel_timeline": [
    { "timestamp": "ISO datetime", "event": "string", "channel": "string" }
  ],
  "device_info": { "device_id": "string", "known_device": "boolean", "location": "string" }
}
```

> **Semantic note that matters more than the schema:** `deepfake_voice_score` and
> `communication_authenticity` are *authenticity* scores — **higher = more likely genuine**.
> `social_engineering_score` is a *risk* score — **higher = worse**. Every team has inverted
> one of these at least once. Write the direction in a comment next to every field you touch.

### 6.3 `RiskAssessment` — produced by B, consumed by C

```json
{
  "transaction_id": "string (uuid)",
  "risk_score": "number 0-100",
  "risk_reasons": ["array of short human-readable strings"],
  "identity_confidence": "number 0-100 (passthrough/refined from SignalBundle)",
  "communication_authenticity": "number 0-100 (passthrough)",
  "intent_confidence": "number 0-100",
  "semantic_drift_score": "number 0-100 (higher = bigger mismatch)",
  "transaction_fingerprint": "string (hash)",
  "fingerprint_status": "MATCH | MISMATCH | NOT_YET_VERIFIED",
  "beneficiary_risk": { "score": "number 0-100", "reasons": ["array"] },
  "behavioral_risk": { "score": "number 0-100", "reasons": ["array"] },
  "decision": "APPROVE | CHALLENGE | BLOCK",
  "recommended_action": "string",
  "investigation_summary": "string (2-5 sentence agent explanation)",
  "requires_out_of_band_verification": "boolean",
  "duress_escalation": "boolean"
}
```

### 6.4 `AuthorizationRecord` — produced by C after human verification, for audit

```json
{
  "transaction_id": "string",
  "executive_id": "string",
  "transaction_fingerprint": "string",
  "verification_method": "OOB_APPROVAL | CHALLENGE_RESPONSE | SECONDARY_APPROVER | NONE",
  "verification_result": "APPROVED | REJECTED | EXPIRED | PENDING",
  "nonce": "string",
  "issued_at": "ISO datetime",
  "expires_at": "ISO datetime",
  "final_outcome": "EXECUTED | BLOCKED | ESCALATED",
  "audit_notes": "string"
}
```

### 6.5 `CapabilityToken` — new in v1.1, produced by B, redeemed by C's mock executor

This is Invariant 9 made concrete. It is the artefact that replaces "the CFO approved
something" with "this exact payment, once, before 14:32, up to ₹10,00,000."

```json
{
  "token_id": "string (uuid)",
  "transaction_id": "string",
  "transaction_fingerprint": "string (sha256 hex, binds the token to exact fields)",
  "scope": {
    "action": "TRANSFER | CREDENTIAL_RESET | BENEFICIARY_CHANGE | PAYMENT_LIMIT_CHANGE",
    "destination_account": "string (exact match required at redemption)",
    "max_amount": "number",
    "currency": "string"
  },
  "issued_at": "ISO datetime",
  "expires_at": "ISO datetime",
  "single_use": true,
  "redeemed_at": "ISO datetime | null",
  "policy_version": "string",
  "mac": "string (HMAC-SHA256 over the canonical serialization, key = INTENTLOCK_HMAC_SECRET)"
}
```

### 6.6 Additive extensions (v1.1) — where the novel work lives

**Rule:** extensions are added as **new top-level keys with mandatory defaults**. Consumers
MUST ignore unknown keys. Producers MUST always emit every extension key, using the default
when the feature is not applicable. This is what lets three agents ship novel features in
parallel without a single integration renegotiation.

**`TransactionIntent` extensions (owner: A)**

| Key | Type | Default | Purpose |
|---|---|---|---|
| `extraction_confidence` | number 0-100 | `0` | How complete/unambiguous the extraction was. |
| `extraction_mode` | `llm\|deterministic\|hybrid\|failed` | `"failed"` | Which path produced this. |
| `deterministic_intent` | object \| null | `null` | Regex/rule-only extraction of the same critical fields, for B's divergence check. |
| `extraction_divergence` | array[string] | `[]` | Fields where LLM and deterministic paths disagree. |
| `injection_flags` | array[string] | `[]` | Detected prompt-injection attempts inside the transcript. |
| `amount_normalization` | object \| null | `null` | `{raw_span, parsed_value, multiplier, rule}` — audit trail for lakh/crore parsing. |
| `language_detected` | string | `"en"` | BCP-47-ish tag; `en-IN-hinglish` permitted. |
| `origin_session_id` | string | `""` | Channel session identity, for Invariant 6. |
| `sample_id` | string \| null | `null` | Scenario ID (e.g. `S06`) when replaying a golden fixture. |

**`SignalBundle` extensions (owner: A)**

| Key | Type | Default | Purpose |
|---|---|---|---|
| `detector_reports` | array[object] | `[]` | `{name, score, confidence, abstain, abstain_reason}` per detector — enables Invariant 3 and ensemble-disagreement scoring. |
| `detector_disagreement` | number 0-100 | `0` | Spread between independent detectors on the same modality. |
| `voice_abstain` / `video_abstain` | boolean | `false` | True when the modality is present but unscoreable. |
| `replay_similarity` | object \| null | `null` | `{max_similarity 0-1, matched_utterance_id, method}` near-duplicate detection. |
| `freshness_token_echoed` | boolean \| null | `null` | Did the response incorporate the live freshness nonce? |
| `channel_switch_flags` | array[string] | `[]` | e.g. `RAPID_SWITCH_3_CHANNELS_11MIN`, `BENEFICIARY_CHANGE_THEN_PAYMENT`. |
| `origin_channel_id` | string | `""` | Concrete channel/session/device triple hash, for Invariant 6. |
| `stylometry_features` | object \| null | `null` | Per-feature deltas so C can render *why* the style score dropped. |

**`RiskAssessment` extensions (owner: B)**

| Key | Type | Default | Purpose |
|---|---|---|---|
| `contribution_table` | array[object] | `[]` | `{factor, raw_score, weight, points, evidence[]}` — the audit trail behind `risk_score`. C renders this as the bar chart. |
| `counterfactuals` | array[object] | `[]` | `{would_be_decision, changes:[{field, from, to}], points_delta}` — "this would have APPROVED if…". |
| `top_blocking_factor` | object \| null | `null` | `{factor, points, plain_english}` — the single biggest reason it did not approve. |
| `intent_confidence_components` | object | `{}` | Named contributions to `intent_confidence`, proving it is independent of voice/video. |
| `hard_overrides_fired` | array[string] | `[]` | e.g. `FINGERPRINT_MISMATCH`, `DURESS`, `SAME_CHANNEL_VERIFICATION`, `BREAKER_TRIPPED`, `AMOUNT_CEILING`. |
| `policy_version` | string | `"0.0.0"` | Semver of the policy pack used. |
| `policy_hash` | string | `""` | SHA-256 of the serialized policy constants — proves reproducibility. |
| `capability_token` | object \| null | `null` | `CapabilityToken` (§6.5), only after successful verification. |
| `cooldown_seconds` | number | `0` | Risk-proportional mandatory delay before execution. |
| `breaker_state` | `CLOSED\|OPEN\|HALF_OPEN` | `"CLOSED"` | Org-level velocity circuit breaker. |
| `secondary_approver_required` | boolean | `false` | Separation-of-duties trigger. |
| `secondary_approver_id` | string \| null | `null` | Collusion-aware selection result. |
| `secondary_approver_rationale` | string | `""` | Why *this* approver (and who was excluded). |
| `comprehension_challenge` | object \| null | `null` | `{type, prompt, options[], expected_answer_hash, ttl_seconds}` issued to C. |
| `channel_independence` | object | `{}` | `{origin_channel_id, required_verification_class, satisfied}`. |
| `extraction_divergence_penalty` | number | `0` | Points added because A's LLM and deterministic paths disagreed. |
| `degraded_mode` | boolean | `false` | True when the decision was reached with no LLM available. |
| `latency_ms` | object | `{}` | Per-stage timing for the SLO panel. |
| `beneficiary_graph` | object \| null | `null` | `{nodes[], edges[]}` subgraph for C's web-of-trust visual. |

**`AuthorizationRecord` extensions (owner: C)**

| Key | Type | Default | Purpose |
|---|---|---|---|
| `comprehension_challenge_result` | object \| null | `null` | `{type, answered_correctly, attempts, elapsed_ms}`. |
| `device_signature` | object \| null | `null` | `{alg:"ECDSA_P256_SHA256", public_key_thumbprint, signature_b64, signed_payload_sha256}` — real WebCrypto signature over the fingerprint. |
| `origin_channel` / `verification_channel` | string | `""` | Invariant 6 evidence. |
| `channel_independent` | boolean | `false` | Machine-checked, not asserted. |
| `audit_seq` | integer | `0` | Monotonic sequence in the hash-chained log. |
| `prev_hash` / `record_hash` | string | `""` | Tamper-evident chain links. |
| `redaction_applied` | boolean | `false` | True when account numbers were tokenized before any LLM call. |
| `capability_token_id` | string \| null | `null` | Which capability was minted/redeemed. |
| `silent_escalation` | boolean | `false` | Duress path taken (never rendered on the operator screen). |

---

## 7. Canonical persona registry (FROZEN — `contracts/personas.json`)

**The single most common way a parallel hackathon build fails is two teams inventing
different personas.** This registry is frozen at hour 0. Team A builds stylometry and duress
against it; Team B builds behavioural baselines against it; Team C displays it. Nobody
invents a name.

Fictional company: **Meridian Steel & Logistics Pvt Ltd**, domain `meridiansteel.example`.

### Executives

```json
[
  {
    "executive_id": "EXE-001",
    "name": "Ananya Rao",
    "role": "Group CFO",
    "email": "ananya.rao@meridiansteel.example",
    "baseline": {
      "median_amount_inr": 800000,
      "p95_amount_inr": 4500000,
      "max_ever_inr": 6200000,
      "normal_hours_ist": "09:00-19:00",
      "normal_weekdays": ["Mon","Tue","Wed","Thu","Fri"],
      "normal_countries": ["IN","SG","AE"],
      "usual_actions": ["TRANSFER","BENEFICIARY_CHANGE"],
      "usual_beneficiaries": ["BEN-001","BEN-002","BEN-005"],
      "initiates_payments_pct": 41
    },
    "devices": [
      {"device_id":"DEV-EXE001-LAPTOP","label":"MacBook Pro (office)","registered":true,"oob_capable":false},
      {"device_id":"DEV-EXE001-PHONE","label":"iPhone 15 (registered authenticator)","registered":true,"oob_capable":true}
    ],
    "duress_scheme": {
      "id": "DURESS_LAST_DIGIT_7",
      "kind": "numeric_substitution",
      "spec": "In a coerced approval, the final digit of the destination account is stated as 7 when the true final digit is not 7.",
      "why_this_design": "An attacker forcing her to read out an account number cannot tell a wrong digit from a mistake, and she can plausibly claim a slip. An obviously odd codeword would be recognised as a duress signal."
    },
    "stylometry_profile_hint": {
      "register": "formal, concise, no exclamation marks",
      "sign_off": "Best regards,\nAnanya",
      "characteristic_phrases": ["please revert", "kindly note", "for your approval"],
      "avg_sentence_words": 14,
      "greeting": "Dear <name>,"
    }
  },
```

```json
  {
    "executive_id": "EXE-002",
    "name": "Vikram Shah",
    "role": "Chief Executive Officer",
    "email": "vikram.shah@meridiansteel.example",
    "baseline": {
      "median_amount_inr": 250000,
      "p95_amount_inr": 1200000,
      "max_ever_inr": 1800000,
      "normal_hours_ist": "08:00-22:00",
      "normal_weekdays": ["Mon","Tue","Wed","Thu","Fri","Sat"],
      "normal_countries": ["IN","GB","US"],
      "usual_actions": ["OTHER"],
      "usual_beneficiaries": ["BEN-005"],
      "initiates_payments_pct": 3
    },
    "devices": [
      {"device_id":"DEV-EXE002-PHONE","label":"Pixel 8 (registered authenticator)","registered":true,"oob_capable":true}
    ],
    "duress_scheme": {
      "id": "DURESS_PHRASE_ROUTINE",
      "kind": "innocuous_token_phrase",
      "spec": "The phrase 'please treat this as routine' appears anywhere in a coerced approval.",
      "why_this_design": "It reads as ordinary corporate hedging, so a coercer hears compliance. The system knows the phrase is semantically contradictory on an urgent high-value request — that contradiction is the signal."
    },
    "stylometry_profile_hint": {
      "register": "warm, longer sentences, occasional em-dash",
      "sign_off": "Thanks,\nVikram",
      "characteristic_phrases": ["let's move fast", "keep me posted", "good stuff"],
      "avg_sentence_words": 22,
      "greeting": "Hi <first_name> —"
    }
  }
]
```

**Rule for both:** `initiates_payments_pct` matters. Vikram (CEO) almost never initiates
payments, so a CEO-originated ₹2.5 crore transfer is behaviourally anomalous *even if the
identity is perfect*. That asymmetry is deliberate — it is the cheapest possible
demonstration that intent risk is independent of identity confidence.

### Employees / operators (the humans who receive the request)

```json
[
  {"employee_id":"EMP-101","name":"Priya Menon","role":"Finance Analyst","trust_score":78,
   "history":{"correct_escalations":6,"missed_frauds":1,"tenure_months":14}},
  {"employee_id":"EMP-102","name":"Rohit Iyer","role":"Treasury Manager","trust_score":91,
   "history":{"correct_escalations":11,"missed_frauds":0,"tenure_months":52}},
  {"employee_id":"EMP-103","name":"Kabir Nair","role":"IT Help Desk","trust_score":54,
   "history":{"correct_escalations":1,"missed_frauds":2,"tenure_months":4}}
]
```

---

## 8. Canonical beneficiary / vendor master (FROZEN — `contracts/beneficiaries.json`)

`org_payment_count` and `paid_by` are what make the **org-wide web of trust** different from
per-executive history. Note `BEN-007`: the org trusts it, this executive has never used it —
that must score *lower* risk than `BEN-003`, which nobody has ever paid.

```json
[
  {"beneficiary_id":"BEN-001","name":"Kalyani Forge Components Pvt Ltd","account":"HDFC0001234567890",
   "first_seen":"2019-04-12","last_modified":"2019-04-12","country":"IN",
   "paid_by":["EXE-001","EMP-101","EMP-102"],"org_payment_count":214,"status":"TRUSTED"},

  {"beneficiary_id":"BEN-002","name":"Sundaram Freight Services","account":"ICIC0009988776655",
   "first_seen":"2021-08-03","last_modified":"2024-11-20","country":"IN",
   "paid_by":["EXE-001","EMP-102"],"org_payment_count":57,"status":"TRUSTED"},

  {"beneficiary_id":"BEN-003","name":"Global Trading FZE","account":"ADCB0000099281",
   "first_seen":"<TODAY>","last_modified":"<NOW-18min>","country":"AE",
   "paid_by":[],"org_payment_count":0,"status":"NEW_TO_ORG"},

  {"beneficiary_id":"BEN-004","name":"Kalyanl Forge Componets Pvt Ltd","account":"HDFC0007777000111",
   "first_seen":"<TODAY>","last_modified":"<TODAY>","country":"IN",
   "paid_by":[],"org_payment_count":0,"status":"SUSPECTED_TYPOSQUAT_OF:BEN-001"},

  {"beneficiary_id":"BEN-005","name":"Meridian Employee Payroll Pool","account":"SBIN0000000001",
   "first_seen":"2017-01-02","last_modified":"2017-01-02","country":"IN",
   "paid_by":["EXE-001","EXE-002","EMP-101","EMP-102"],"org_payment_count":1180,"status":"TRUSTED"},

  {"beneficiary_id":"BEN-006","name":"Orion Metals DMCC","account":"EBIL0000445566",
   "first_seen":"2023-02-14","last_modified":"<NOW-2h>","country":"AE",
   "paid_by":["EMP-102"],"org_payment_count":12,"status":"RECENTLY_MODIFIED"},

  {"beneficiary_id":"BEN-007","name":"Zenith Marine Supplies","account":"AXIS0004411223",
   "first_seen":"2024-06-19","last_modified":"2024-06-19","country":"IN",
   "paid_by":["EMP-102"],"org_payment_count":9,"status":"TRUSTED_NEW_TO_EXECUTIVE"}
]
```

`<TODAY>`, `<NOW-18min>`, `<NOW-2h>` are resolved at load time by the shared clock helper so
the "modified 18 minutes ago" demo is always true, whenever you present. **Do not hard-code
dates here** — a stale date silently kills the strongest beneficiary-risk demo.

---

## 9. Money, language and locale rules (FROZEN — `contracts/money.py` shape)

Indian financial language is where a naive parser produces a hilarious 100× error live on
stage. Team A implements the parser; Team B validates the result independently.

| Input form | Multiplier | Notes |
|---|---|---|
| `k`, `K`, `thousand` | 1e3 | |
| `L`, `l`, `lac`, `lakh`, `lakhs`, `lac(s)`, `पंद्रह लाख`, `pandrah lakh` | 1e5 | Hinglish numerals must resolve. |
| `cr`, `Cr`, `crore`, `crores`, `karod` | 1e7 | |
| `2,50,00,000` | — | Indian grouping: 2-2-3 from the right, **not** 3-3-3. |
| `₹`, `Rs`, `Rs.`, `INR`, `rupees` | — | All map to `currency: "INR"`. |
| `$`, `USD` | — | `currency: "USD"`, no implicit FX conversion — record both. |

Hard rules: never silently round; always emit `amount_normalization` with the raw matched
span and the rule applied; if two different amounts appear in one message, extract the one
attached to the payment verb and record the other in `extraction_divergence`; refuse to guess
when the multiplier is absent and the number is ambiguous (`"transfer 50 to Global"` →
`amount: null`, `extraction_confidence` low, downstream `CHALLENGE`, never `APPROVE`).

---

## 10. Canonical scenario matrix (FROZEN — `contracts/scenarios.json`)

**This table is the contract between the three teams and the thing that makes a 24-hour
parallel build possible.** It is frozen at hour 0, *before any code exists*. Team A produces
these samples, Team B's tests assert these decisions, Team C's demo buttons load these IDs.
Team B and C do **not** wait for Team A: hand-written golden fixtures for every row land in
`contracts/golden/` in the first hour (see `04_...md` §2).

Legend — **Class:** `ATTACK` counts toward attack-block rate; `LEGIT` counts toward
legitimate-approval success and false-challenge rate. **HERO** = one of the four scenarios we
actually demo live; everything else is in the benchmark run.

| ID | Scenario | Channel | Actors | Class | Expected decision | Proves |
|---|---|---|---|---|---|---|
| `S01` | Routine vendor payment, ₹6,40,000 | EMAIL | EXE-001 → BEN-001 | LEGIT | `APPROVE`, no friction | We are not a universal blocker |
| `S02` | Genuine high-value ₹42,00,000 to known vendor | VIDEO | EXE-001 → BEN-002 | LEGIT | `CHALLENGE` → `APPROVE` after OOB | Proportionate friction |
| `S03` | Deepfake voice, "CFO" urgent ₹2.5 crore | PHONE | fake EXE-001 → BEN-003 | ATTACK | `BLOCK` | A perfect voice is not authority |
| `S04` | Replay of genuine recorded audio | PHONE | real EXE-001 audio, reused | ATTACK | `BLOCK` | **HERO 4** — authenticity 94 and still blocked |
| `S05` | Compromised mailbox, off-register style | EMAIL | fake EXE-002 → BEN-003 | ATTACK | `BLOCK` | Stylometric twin catches BEC with no audio to fake |
| `S06` | Tampering: ₹10,00,000→BEN-001 becomes ₹1,00,00,000→BEN-003 after approval | VIDEO | EXE-001 | ATTACK | `BLOCK` via `FINGERPRINT_MISMATCH` | **HERO 1** — the thesis |
| `S07` | Beneficiary account changed 18 minutes ago | CHAT | EXE-001 → BEN-003 | ATTACK | `BLOCK` | Beneficiary quarantine |
| `S08` | Pressure stack: urgency + secrecy + authority + bypass | PHONE | fake EXE-002 | ATTACK | `BLOCK` | Social-engineering language model |
| `S09` | Real executive, physically coerced, duress marker present | PHONE | real EXE-001 → BEN-003 | ATTACK | looks like `APPROVE`, emits `SILENT_ESCALATION` | **HERO 2** — the only humane answer |
| `S10` | Transcript contains prompt injection at our extractor | EMAIL | attacker | ATTACK | `BLOCK`, `injection_flags` populated | Our own AI is hardened |
| `S11` | Homoglyph vendor "Kalyanl Forge Componets" | EMAIL | EXE-001 → BEN-004 | ATTACK | `BLOCK` | Real-world BEC technique |

| ID | Scenario | Channel | Actors | Class | Expected decision | Proves |
|---|---|---|---|---|---|---|
| `S12` | Same "CFO" sprays 4 requests at 4 employees in 9 minutes | CHAT ×4 | fake EXE-001 | ATTACK | `BLOCK` + `breaker_state: OPEN` | Org-level velocity control |
| `S13` | Attacker answers the verification on the channel they control | PHONE | fake EXE-001 | ATTACK | verification **refused**, `SAME_CHANNEL_VERIFICATION` | Invariant 6 is enforced, not labelled |
| `S14` | Requester nominates a secondary approver from the same thread | COLLAB_PLATFORM | fake EXE-002 | ATTACK | approver re-selected, rationale emitted | Separation of duties survives collusion |
| `S15` | 3-second noisy clip — detector abstains | PHONE | EXE-001 | LEGIT | `CHALLENGE`, never `APPROVE` | **HERO 3** — unavailable ≠ clean |
| `S16` | Authorization nonce replayed after expiry | — | EXE-001 | ATTACK | `REJECTED` / `EXPIRED` | Replay + expiry binding |
| `S17` | "CEO" asks help desk for a credential reset | PHONE | fake EXE-002 → EMP-103 | ATTACK | `CHALLENGE` + mandatory OOB | Non-payment privileged actions count |
| `S18` | Request to raise the payment approval limit | COLLAB_PLATFORM | fake EXE-001 | ATTACK | `BLOCK` | Attacks on the control itself |
| `S19` | Monthly payroll run to the payroll pool | CHAT | EMP-102 → BEN-005 | LEGIT | `APPROVE`, no friction | Zero false friction on routine work |
| `S20` | Genuine urgent request handled by a high-trust operator | PHONE | EXE-001 → BEN-002 via EMP-102 | LEGIT | `CHALLENGE`-lite → `APPROVE` | Adaptive friction / anti-alert-fatigue |
| `S21` | "Transfer pandrah lakh to Kalyani Forge" (Hinglish) | CHAT | EXE-001 → BEN-001 | LEGIT | `APPROVE` with `amount = 1500000` | Locale correctness |
| `S22` | "Transfer some money soon, will confirm later" | CHAT | EXE-001 | LEGIT | `CHALLENGE` (clarify) | Graceful degradation, not a crash and not a block |

**Counts:** 14 `ATTACK` (`S03`–`S14`, `S16`–`S18`), 8 `LEGIT` (`S01`, `S02`, `S15`, `S19`–`S22`).
Of the `LEGIT` set, exactly three must reach `APPROVE` with **zero** friction (`S01`, `S19`,
`S21`); the other five are *justified* friction and do not count as false challenges.

**Target scorecard we are aiming to put on a slide:** attack-block rate **14/14**,
legitimate-approval success **8/8** (after OOB where required), false-challenge rate **0/3**,
median verification time **< 3 s** offline, prevented fraudulent value **₹4.38 crore**
(sum of `ATTACK` amounts). If a build cannot hit these, fix the build — do not soften the
scenarios.

---

## 11. Differentiator catalogue — 30 items, assigned and tiered

The original brief listed eight novel ideas. This build carries **thirty**, each assigned to
the workstream that can implement it with the least cross-team coupling. Every item is tagged
`[NOVEL-Nxx]` at its exact build site in the team prompts, so nothing is lost between
building and pitching.

**Tiers.** `P0` = the demo does not exist without it. `P1` = the win layer; this is what beats
the other teams. `P2` = stretch; cut at the T+19 freeze without regret and without mentioning
it on stage.

| # | Differentiator | Owner | Tier | Why it wins |
|---|---|---|---|---|
| N1 | **Duress / coercion signal** — pre-registered distress modifier that looks like approval and silently escalates | A detect · B policy · C dual UI | **P0** | The only design in the room that protects a real executive with a gun to their head. Judges remember it. |
| N2 | **Executive stylometric twin** — per-executive linguistic fingerprint | A | **P0** | Catches BEC where there is no audio or video to deepfake at all. |
| N3 | **Semantic drift score** — continuous distance between what was said and what was encoded | B | **P0** | Replaces a boolean with a graded, visual, arguable number. |
| N4 | **Canary / integrity transactions** — synthetic probes proving the control enforces | C | P1 | Proof the control is live, not shelfware. Almost nobody demos this. |
| N5 | **Org-wide beneficiary web of trust** — has *anyone* in finance ever paid this account | B compute · C render | **P0** | Turns per-user history into institutional memory; distinguishes `BEN-003` from `BEN-007`. |
| N6 | **Adaptive friction / employee trust score** — earned lower friction, anti-alert-fatigue | C | P2 | Answers "won't staff just click through everything?" |
| N7 | **Commitment-first OOB reveal** — hash + one-line summary, details on tap | C | P1 | Shoulder-surfing and notification-preview leakage, handled. |
| N8 | **Audit explainability chatbot** — ad hoc Q&A over the audit trail | C | P1 | Speaks directly to the auditor/compliance persona in the brief. |
| N9 | **Proof-of-comprehension challenge** — the executive must reproduce a fact *derived from* the transaction, not just tap yes | B issue/validate · C UI | **P1** | The literal answer to "authentication does not establish intent." Consent proves presence; comprehension proves intent. |
| N10 | **Dynamic linking with a real device signature** — WebCrypto ECDSA P-256 keypair on the "executive phone" signs the transaction fingerprint; B verifies | C sign · B verify | **P1** | Real cryptography, not a mocked button. Mirrors PSD2-style dynamic linking and FIDO transaction confirmation. |
| N11 | **Single-use, scope-limited capability token** — approval mints authority for *this* account, *this* ceiling, *once* | B | **P1** | Reframes the product from "fraud scoring" to "authorization service." Kills standing authority. |
| N12 | **Counterfactual explanations** — "this would have APPROVED if the payee were >30 days old and the amount under ₹40 lakh" | B compute · C render | **P1** | The single most memorable explainability moment available at this cost. |
| N13 | **Adversarial benchmark harness** — runs all 22 scenarios and prints the five organizer-named metrics, plus a threshold sweep | C | **P1** | Hackathon teams show demos; we show a measured confusion matrix and a chosen operating point. |
| N14 | **Prompt-injection hardening of our own extractor** — the transcript is untrusted data, with a dedicated attack scenario | A | **P1** | Cybersecurity track. Nobody else will have threat-modelled their own LLM. |
| N15 | **Dual-path extraction divergence** — LLM extraction cross-checked against a deterministic parser; disagreement is itself a risk signal | A emit · B score | **P1** | Makes Invariant 2 structural rather than aspirational. |

| # | Differentiator | Owner | Tier | Why it wins |
|---|---|---|---|---|
| N16 | **Calibrated abstention — "unavailable ≠ clean"** — an abstaining detector contributes zero authenticity, never favourable evidence | A emit · B enforce | **P1** | Directly answers the brief's "noisy audio, short utterances" failure mode. Invariant 3. |
| N17 | **Detector-ensemble disagreement as a signal** — two independent detectors that disagree raise risk instead of averaging out | A | P1 | Correct epistemics, ~30 lines of code. |
| N18 | **Replay defence: near-duplicate utterance hashing + live freshness token** — verbatim re-use is detected; a fresh unpredictable fact must be echoed | A near-dup · B freshness binding | **P1** | Recorded audio cannot answer a question invented one second ago. |
| N19 | **Risk-proportional cooldown + org velocity circuit breaker** — urgency is the attack, so we price it | B | **P1** | "If it is genuine, it will still be genuine in six minutes." Attacks the attacker's mechanic, not their artefact. |
| N20 | **Homoglyph / typosquat beneficiary detection** — Unicode-confusable normalization + edit distance against the vendor master | B | **P1** | A real BEC technique, visibly caught, in a demo scenario. |
| N21 | **Enforced channel independence** — verification arriving on the origin channel/session/device is refused in code | B enforce · C display | **P1** | Turns a UI label into a machine-checked control. Invariant 6. |
| N22 | **Collusion-aware secondary approver selection** — never someone in the same thread or contacted by the requester in the last window | B | P2 | Defeats "socially engineer both approvers at once." |
| N23 | **Hash-chained tamper-evident audit log** — `prev_hash` chain, published head hash, live "watch me edit a record and the chain turns red" demo | C | **P1** | Converts an audit table into a provable artefact in 40 seconds of stage time. |
| N24 | **Policy-as-code versioning + reproducible replay** — every decision carries `policy_version` + `policy_hash`; `POST /v1/replay` reproduces it byte-identically | B | **P1** | Invariant 8. The answer to "how would a regulator audit this?" |
| N25 | **Degraded mode — decide with the AI dead** — the deterministic core reaches the same decision on all four hero scenarios with the LLM unplugged | B core · C demo | **P1** | We delete our own API key on stage and the control still works. Highest-impact 30 seconds in the pitch. |
| N26 | **PII tokenization before any model call** — account numbers replaced with stable tokens before reaching the audit chatbot | C | P1 | Privacy posture that survives a DPDP-aware question. |
| N27 | **Judge sandbox — "break it yourself"** — a panel where the judge edits amount, payee, urgency or injects text and watches the decision and reasons update live | C | **P1** | Converts a passive judge into a participant. Wins ties. |
| N28 | **Latency / SLO instrumentation** — per-stage `p50/p95`, because "verification time" is a scored metric | B emit · C render | P2 | Cheap credibility. |
| N29 | **Indian locale correctness** — lakh/crore, 2-2-3 digit grouping, Hinglish numerals, refusal to guess ambiguous amounts | A | **P1** | A 100× parsing error live on stage is fatal; getting it right is a quiet, specific competence signal. |
| N30 | **Attack-cost ledger** — a table showing, per attacker capability, what still blocks them | pitch (shared) | **P1** | The slide that makes defence-in-depth legible in eight seconds. |

**Tier totals:** P0 = 5 · P1 = 22 · P2 = 3. If you are behind at T+17, cut in this order:
N28, N6, N22, then the graph rendering half of N5, then N26. **Never cut** N9, N10, N12, N13,
N23, N25, N27 — those are the differentiators the pitch is built on.

### Split-ownership suffix convention (use these ids in code comments and commit messages)

Eleven differentiators are split across teams. Each half gets a letter suffix so a
`[NOVEL-…]` tag in a source file names **one owner and one deliverable**, never a shared
aspiration. This table is the single source of truth for those ids.

| Id | Half | Owner |
|---|---|---|
| `N1a` / `N1b` / `N1c` | detect the distress marker / silent-escalation policy / dual UI | A / B / C |
| `N5a` / `N5b` | compute the web of trust / render the trust graph | B / C |
| `N9a` / `N9b` | issue and validate the comprehension challenge / challenge UI | B / C |
| `N10a` / `N10b` / `N10c` | canonical fingerprint and dynamic linking / verify the device signature / generate the keypair and sign in the browser | B / B / C |
| `N12a` / `N12b` | compute counterfactuals / render them | B / C |
| `N15a` / `N15b` | emit both extraction paths and agreement flags / score the divergence | A / B |
| `N16a` / `N16b` | emit abstention honestly / enforce renormalization and the coverage floor | A / B |
| `N18a` / `N18b` | near-duplicate detection and freshness issue / bind and validate freshness | A / B |
| `N21a` / `N21b` | enforce channel independence in code / display it | B / C |
| `N25a` / `N25b` | deterministic core that decides without the LLM / the on-stage kill switch | B / C |
| `N28a` / `N28b` | emit per-stage latency / render the SLO panel | B / C |

Unsuffixed ids (`N2`, `N3`, `N11`, `N13`, `N14`, `N17`, `N19`, `N20`, `N22`, `N23`, `N24`,
`N26`, `N27`, `N29`) have exactly one owner and are never suffixed. `N30` belongs to the pitch.

**`intent_confidence` vs `identity_confidence` is not a numbered differentiator — it is the
central thesis (§1).** Tag it `[CENTRAL THESIS]`, not `[NOVEL-Nxx]`, so nobody cuts it while
triaging the differentiator list.

---

## 12. Metric definitions (FROZEN — these exact formulas go on the results slide)

The brief names five metrics. Defining them precisely — including admitting which frictions
are *justified* — is itself a differentiator. Vague metrics read as marketing.

```
attack_block_rate            = attacks whose outcome ∈ {BLOCK, SILENT_ESCALATION, REFUSED, EXPIRED}
                               ────────────────────────────────────────────────────────────────
                                                    total attacks (14)

legitimate_approval_success  = legit scenarios that reach a final APPROVE
                               (directly, or after a successful OOB verification)
                               ─────────────────────────────────────────────────
                                                total legit (8)

false_challenge_rate         = legit scenarios whose EXPECTED outcome is a frictionless
                               APPROVE but which received CHALLENGE or BLOCK
                               ──────────────────────────────────────────────────────
                                  legit scenarios expected to be frictionless (3)

verification_time_ms         = median wall-clock from communication ingest to a rendered
                               decision, measured in INTENTLOCK_MODE=offline
                               (report p50 and p95; state the mode on the slide)

prevented_fraudulent_value   = Σ amount over attacks whose outcome ≠ EXECUTED
                               (report in ₹ crore, and state that amounts are synthetic)
```

Two honesty rules the judges will respect: (1) a `CHALLENGE` on a genuine request is **not**
counted as a success *or* a failure unless the scenario expected frictionless approval — say
this out loud; (2) `prevented_fraudulent_value` is a synthetic figure and must be labelled as
such on the slide. Inflating it is the fastest way to lose a cybersecurity judge.

---

## 13. Repository layout, ports and environment (FROZEN)

One monorepo. Three directories that never collide. One command to run everything.

```
intentlock/
├── Makefile                  # shared — make demo | test | conformance | bench | freeze
├── docker-compose.yml        # shared — optional, `make demo` must work without Docker too
├── .env.example              # shared — every key, all values empty
├── contracts/                # shared, FROZEN
│   ├── schemas/*.json        # JSON Schema for the 5 contracts (base + extensions)
│   ├── personas.json         # §7
│   ├── beneficiaries.json    # §8
│   ├── scenarios.json        # §10
│   └── golden/               # S01..S22 hand-written fixtures: intent, signals, expected decision
├── packages/signal/          # TEAM A ONLY
├── packages/core/            # TEAM B ONLY
├── apps/console/             # TEAM C ONLY (React + Vite + TS)
├── services/audit/           # TEAM C ONLY (FastAPI: audit chain, chatbot, canary, bench)
├── tests/conformance/        # shared — one test per Invariant, all teams run it
└── docs/
    ├── STYLOMETRY.md         # A
    ├── RISK_WEIGHTS.md       # B
    ├── THREAT_MODEL.md       # C, reviewed by B
    ├── DEMO_SCRIPT.md        # C
    └── CHANGES.md            # any contract deviation, with timestamp and initials
```

### Ports and endpoints (FROZEN — hard-coding these avoids an hour of integration pain)

| Service | Port | Endpoints |
|---|---|---|
| A — signal | `8001` | `POST /v1/process-communication`, `POST /v1/extract`, `POST /v1/analyze-signals`, `GET /v1/samples`, `GET /v1/samples/{id}`, `GET /healthz` |
| B — core | `8002` | `POST /v1/assess-risk`, `POST /v1/fingerprint/compute`, `POST /v1/fingerprint/verify`, `POST /v1/challenge/issue`, `POST /v1/challenge/validate`, `POST /v1/authorization/verify`, `POST /v1/token/mint`, `POST /v1/token/redeem`, `POST /v1/replay`, `GET /v1/policy`, `GET /healthz` |
| C — audit | `8003` | `POST /v1/audit/append`, `GET /v1/audit`, `GET /v1/audit/{tx}`, `POST /v1/audit/verify-chain`, `POST /v1/audit/tamper` *(demo only)*, `POST /v1/audit/ask`, `POST /v1/canary/run`, `POST /v1/bench/run`, `GET /healthz` |
| C — console | `5173` | Vite dev server. Routes: `/`, `/tx/:id`, `/device`, `/security`, `/audit`, `/bench`, `/sandbox` |

Every service enables CORS for `http://localhost:5173`, `:8001`, `:8002`, `:8003`. Every
service implements `GET /healthz` returning `{"ok": true, "service": "...", "version": "...",
"mode": "live|cached|offline", "policy_version": "..."}`. `make demo` polls all three
`/healthz` before opening the browser.

### Environment variables (FROZEN prefix `INTENTLOCK_`)

| Variable | Default | Meaning |
|---|---|---|
| `INTENTLOCK_MODE` | `offline` | `live` = call the LLM · `cached` = replay golden LLM responses · `offline` = deterministic only. **Default is `offline` so a judge's clean clone works with no key.** |
| `INTENTLOCK_LLM_PROVIDER` | `anthropic` | `anthropic\|openai\|openrouter\|none` — behind one interface. |
| `INTENTLOCK_LLM_API_KEY` | *(empty)* | Absent ⇒ silently fall back to `offline`, never crash. |
| `INTENTLOCK_LLM_MODEL` | *(provider default)* | |
| `INTENTLOCK_SEED` | `1337` | Seeds every RNG. |
| `INTENTLOCK_HMAC_SECRET` | `dev-only-not-a-secret` | Capability-token MAC key. |
| `INTENTLOCK_AUTH_TTL_SECONDS` | `600` | Fingerprint/authorization validity window. |
| `INTENTLOCK_CHALLENGE_TTL_SECONDS` | `120` | Comprehension-challenge window. |
| `INTENTLOCK_POLICY_VERSION` | `1.0.0` | |
| `INTENTLOCK_A_URL` / `_B_URL` / `_C_URL` | `http://localhost:800{1,2,3}` | |
| `INTENTLOCK_TZ` | `Asia/Kolkata` | |

**Mode semantics are a graded contract, not a boolean.** `offline` must produce a *complete
and correct* run of all 22 scenarios — the LLM only enriches `investigation_summary`,
extraction of unusual phrasings, and the audit chatbot. If any decision changes between
`offline` and `live`, that is a bug in the deterministic core, not a feature.

---

## 14. Error taxonomy and fail-safe direction (FROZEN)

Every failure has exactly one prescribed direction, and the direction is always **toward
friction, never toward approval**. Any code path that turns an error into `APPROVE` is a
critical bug.

| Condition | Code | Behaviour |
|---|---|---|
| LLM unreachable / no key / timeout | `LLM_UNAVAILABLE` | Fall back to deterministic path, set `degraded_mode: true`, continue. Not an error to the user. |
| LLM returns unparseable output | `EXTRACTION_MALFORMED` | Retry once with a stricter prompt, then deterministic path, `extraction_mode: "failed"`, `extraction_confidence: 0` ⇒ minimum `CHALLENGE`. |
| Required field missing after both paths | `INTENT_INCOMPLETE` | `CHALLENGE` for clarification. **Never** `APPROVE`, **never** a 500. |
| Detector cannot score the modality | `DETECTOR_ABSTAIN` | `abstain: true`, contributes **zero** authenticity (Invariant 3). |
| Upstream service (A or B) down | `UPSTREAM_UNAVAILABLE` | C falls back to `contracts/golden/`, shows a visible "cached fixture" badge. Never a blank screen in front of a judge. |
| Fingerprint recompute differs | `FINGERPRINT_MISMATCH` | Hard override ⇒ `BLOCK` (Invariant 4). |
| Verification arrives on origin channel | `SAME_CHANNEL_VERIFICATION` | Refuse the verification (Invariant 6). |
| Nonce reused or expired | `NONCE_REPLAY` / `AUTH_EXPIRED` | Reject; require re-issuance. |
| Capability token scope violated at redemption | `TOKEN_SCOPE_VIOLATION` | Refuse execution, log, alert. |
| Audit chain verification fails | `AUDIT_CHAIN_BROKEN` | Banner on every screen; the demo *shows* this deliberately once. |
| Injection detected in transcript | `PROMPT_INJECTION_SUSPECTED` | Strip, flag, score as risk, continue with deterministic extraction only. |

---

## 15. Glossary (use these words on stage; they are precise and they land)

- **Communication identity** — proof about the channel, account or device. What everyone else
  authenticates.
- **Transaction intent** — proof that a specific human knowingly authorised specific terms.
  What we authorise.
- **Dynamic linking** — cryptographically binding an authentication artefact to the exact
  amount and payee, so the artefact is worthless for any other transaction.
- **Transaction fingerprint** — SHA-256 over a canonical serialization of the critical fields.
- **Semantic drift** — graded distance between what was said and what was encoded.
- **Comprehension challenge** — a question answerable only by someone who actually read the
  transaction. Distinguishes intent from consent.
- **Capability token** — single-use, scope-bound authority. The opposite of a standing approval.
- **Abstention** — a detector declining to score. Evidence of nothing, never evidence of
  innocence.
- **Silent escalation** — the duress path: normal-looking to the actor, alarming to security.
- **Degraded mode** — full decision quality with no model available.
- **Attack-cost ledger** — per attacker capability, what still stops them.

---

## 16. The 24-hour clock (shared; each team prompt repeats its own lane)

`T+0` is the moment the three agents start. Every gate is a **hard** gate: if you are not at
the gate, cut P2 work immediately rather than pushing the gate.

| Gate | Time | What must be true |
|---|---|---|
| **G0 — Freeze** | `T+0 → T+0:45` | `contracts/` fully populated: schemas, personas, beneficiaries, scenarios, **and all 22 golden fixtures hand-written**. Nobody writes feature code before this lands. |
| **G1 — Stubs** | `T+1:30` | All three services return schema-valid *fake* responses on their real ports. C can render a dashboard from A and B stubs. Integration risk is now zero. |
| **G2 — Vertical slice** | `T+4:30` | `S06` (the hero tampering scenario) runs end-to-end A→B→C with real logic. One scenario working beats six half-built ones. |
| **G3 — P0 complete** | `T+10` | All P0 items from §11 done; `S01`–`S11` produce correct decisions; `make conformance` green on Invariants 1–7. |
| **G4 — P1 complete** | `T+16` | All P1 items done; all 22 scenarios correct; Invariants 8–9 green; benchmark harness produces the scorecard. |
| **G5 — Freeze & cache** | `T+19` | Code freeze. Run all 22 scenarios in `live` mode once, cache every LLM response into `contracts/golden/llm/`, then switch the demo to `offline`. **No feature commits after this point.** |
| **G6 — Rehearsal** | `T+20 → T+22` | Full pitch rehearsed **three times** on the actual demo laptop, on the venue network, with the projector resolution. Time it. Trim to 80% of the slot. |
| **G7 — Buffer** | `T+22 → T+24` | Slides, README, `THREAT_MODEL.md`, Q&A drill. Do not code. |

**The single most expensive mistake available to this team is a late integration.** G1 exists
to make integration a non-event: after `T+1:30`, every team is developing against a live,
schema-valid version of the others.

---

## 17. Global definition of done

The build is done when all of the following are simultaneously true:

1. `make demo` on a clean clone, **with no `.env` and no network**, brings up all three
   services and opens the console in under two minutes.
2. `make conformance` passes — one green test per Invariant, nine for nine.
3. `make bench` prints the five metrics from §12 and writes `docs/RESULTS.md`.
4. All 22 scenarios in §10 produce their expected decision, in `offline` mode, twice in a row,
   byte-identically.
5. The four hero scenarios (`S06`, `S09`, `S15`, `S04`) can be clicked in any order without a
   reload, and each lands on a screen a judge understands within five seconds without
   narration.
6. `docs/DEMO_SCRIPT.md`, `docs/THREAT_MODEL.md`, `docs/RISK_WEIGHTS.md`,
   `docs/STYLOMETRY.md`, `docs/RESULTS.md` exist and are current.
7. No raw JSON is visible anywhere in the demo path.
8. Nothing on screen claims a capability the code does not have.

---

## 18. Where to go next

- Team A → `01_TEAM_A_SIGNAL_INTELLIGENCE.md`
- Team B → `02_TEAM_B_RISK_FUSION_CORE.md`
- Team C → `03_TEAM_C_VERIFICATION_DASHBOARD_DEMO.md`
- Integrator → `04_INTEGRATION_AND_CONFORMANCE.md`
- Whoever pitches → `05_PITCH_AND_JUDGING.md`


















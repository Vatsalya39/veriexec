# INTENTLOCK — Risk Weights & Policy Constants (Team B)

> Every threshold that can change a decision, with the source of the number. This document
> is final at G5. A judge skims it in ninety seconds; the summary table is the first thing
> they see. Every constant named here lives in `packages/core/policy/constants.py` and is
> hashed into `policy_hash` — served live at `GET /v1/policy`.

## 1. The seven dimensions

| Dimension | Weight | Why that weight |
|---|---|---|
| `beneficiary` | **0.20** | The payee and the account are the only fields where the attacker's *goal* lives. A deepfake is a delivery mechanism; the destination account is the crime. Same reasoning banks use for beneficiary whitelisting. |
| `communication_authenticity` | 0.15 | Media evidence matters, but it is spoofable by construction — a perfect clone scores 0 here and still blocks on the account. |
| `social_engineering` | 0.15 | Urgency, secrecy, authority, bypass — the pressure families. Priced equal to authenticity because they are orthogonal to it. |
| `behavioural` | 0.15 | Amount/time/novelty deviation from the persona's own history. |
| `semantic_drift` | 0.15 | Graded distance between what was said and what is being executed. |
| `identity_confidence` | 0.10 | Device/account posture. Necessary, never sufficient. |
| `device_channel` | 0.10 | Channel-independence verdict plus switch-pattern flags. |

Weights sum to 1.00 — asserted at import and by test.
Source: **chosen and calibrated against the 22 frozen fixtures** (`S01`–`S22`), not measured
from a real portfolio. That is an honest calibration basis for a prototype and a limitation
for production (see §7).

## 2. Bands, floors and the uncertainty price

| Constant | Value | Source |
|---|---|---|
| `BANDS` | 0–29 APPROVE · 30–69 CHALLENGE · 70–100 BLOCK | Spec §16.1, frozen. |
| `MIN_COVERAGE` | 0.55 | Below 55 % of risk weight present, nothing can be approved (Invariant 6). Chosen so that a fully-abstained media pair (0.30 of weight gone) still leaves an approvable remainder, but a missing bundle does not. |
| `UNCERTAINTY_PENALTY` | 0.30 | Missing evidence is charged at 30 % of the missing weight. Not knowing is worse than knowing it is fine — renormalizing alone would make an abstention *neutral*. |
| `BEHAVIOURAL_CAP` | 92 | Behaviour alone can never reach the BLOCK band; blocking on behaviour alone is where false-challenge rates come from. |
| `REPLAY_RISK_APPROVE_CEILING` | 40 | PC-5: a near-duplicate (similarity ≥ 0.92 rescaled to 80+) is never routine. |
| `LOW_VALUE_EXEMPT` | ₹50,000 (paise) | PC-4: routine small payments do not need a second channel. |
| `ABSOLUTE_SINGLE_TXN_CEILING` | ₹20,00,000 | HO-2's organizational cap. |
| Relative ceiling | 2.5 × the person's median | `min()` of the two — neither a low-volume nor high-volume executive inherits the other's cap. |
| `CHALLENGE_ATTEMPTS_ALLOWED` | 2 | One wrong answer is still answerable; two is a refusal (HO-5). |

## 3. The eight hard overrides (frozen order, first match wins)

| Order | Id | Fires when | Why this position |
|---|---|---|---|
| 1 | HO-1 | Fingerprint MISMATCH | The thesis. The most specific, most explainable reason must be the one the operator reads — if HO-3 fired first on an S06-family case, you would show a homoglyph message when the real story is a changed account. |
| 2 | HO-2 | Unregistered account + amount over ceiling | Right company, wrong account, large amount: the real vendor-impersonation shape. |
| 3 | HO-3 | Homoglyph skeleton collision (or high-confidence near-miss on an established payee) | S11. |
| 4 | HO-4 | Nonce replayed or token spent | A categorical statement that this authorization was already consumed. |
| 5 | HO-5 | Comprehension challenge exhausted | Two wrong answers about the transaction's own facts. |
| 6 | HO-6 | Device signature INVALID or REVOKED | Dynamic linking failed at the cryptographic layer. |
| 7 | HO-7 | Sanctions screen ≠ clear | Compliance sign-off exists precisely for this. |
| 8 | HO-8 | Token minted under a stale policy version | "What happens when your rules change mid-flight?" — re-authorize. |

## 4. The six APPROVE preconditions

`APPROVE` is "risk was low AND all of these held": PC-1 fingerprint MATCH · PC-2 coverage ≥
0.55 · PC-3 no duress · PC-4 channel-independent (or ≤ ₹50,000) · PC-5 replay risk < 40 ·
PC-6 breaker CLOSED. A failed precondition degrades to CHALLENGE with a reason that names
the remedy — from a closed vocabulary (`REQUIRED_ACTIONS`), because C maps each entry to a
button.

## 5. Abstention arithmetic (why absence raises risk)

With `k` of the seven dimensions abstaining, the fused score is:

```
score = (Σ present weighted scores / coverage) + 0.30 × (1 − coverage) × 100
```

Renormalization over present weight alone would make an abstention *lower* the average when
the abstained dimension was risky — the exact bug that turns a broken microphone into an
approval. The added penalty makes ignorance cost something. Worked case: all media abstains
(0.30 of weight gone), coverage = 0.70, penalty = 9 points — S15 therefore lands mid-CHALLENGE
with authenticity unmeasured, which is the intended reading of "unavailable ≠ clean".

## 6. Worked example — S06 (tampering after genuine approval)

Approved: ₹45,00,000 → Kalyani Forge (BEN-001) at account …4471. Requested: same amount,
same payee, account …9982.

| Dimension | Raw | Weight | Points |
|---|---|---|---|
| social_engineering | 70 | 0.15 | 10.50 |
| beneficiary | 45 | 0.20 | 9.00 |
| semantic_drift | 30 | 0.15 | 4.50 |
| behavioural | 23 | 0.15 | 3.41 |
| identity_confidence | 9 | 0.10 | 0.90 |
| communication_authenticity | 4 | 0.15 | 0.60 |
| device_channel | 0 | 0.10 | 0.00 |
| **fused** | | | **29.0** |

Drift scores the account field at 100 (0.30 weight of the drift composite) with the amount,
payee and action equal — the tampered account is the whole story.

The fused score sits **inside the APPROVE band**, and the decision is still **BLOCK —
HO-1**, because the recomputed fingerprint does not match the approved one. These are the
exact numbers the tests assert. This is the prepared answer, verbatim:

> "The weighted score is 29 — an approve band. We block anyway, because the account in the
> request is not the account bound to the captured intent. That is not a probabilistic
> judgement we can average against other evidence; it is a categorical fact. Scores are for
> graded evidence. Overrides are for facts. If we let a 29 average its way past a hash
> mismatch, the fingerprint would be decorative."

`intent_confidence` for S06 = 100 − 45.6 ≈ 54, then **capped at 25** by the MISMATCH rule
(components: drift 10.5, fingerprint 20.0, beneficiary 4.5, behavioural 3.4, rest ≤ 1).
Voice authenticity is 96/100. Those two numbers side by side are the pitch.

## 7. Known limitations (stated before anyone asks)

- Baselines are synthetic, generated from the frozen persona registry. No real ERP history
  backs a single median.
- Weights are calibrated on 22 hand-authored fixtures, not a real portfolio. No ROC
  analysis has been performed; the threshold sweep C runs is a smoke test, not an evaluation.
- The homoglyph table covers ~30 high-frequency confusables, not the full Unicode
  confusables set.
- The authorization reference pre-image is caller-supplied on the assess path until B2's
  server-side store owns it; a caller cannot manufacture a MATCH (the hash is recomputed
  locally), but the artefact's provenance is the caller's word.
- `policy_hash` covers the policy files and the two data contracts; it does not cover the
  service transport, which adds no policy (tested by byte-comparison).

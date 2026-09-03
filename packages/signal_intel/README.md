# INTENTLOCK — Team A: Signal Intelligence & Extraction Layer

> *"We do not trust the transcript, we do not trust our own language model, and we do
> not treat a detector's silence as a clean bill of health."*

The senses of INTENTLOCK: raw communication in, two clean contract artefacts out —
a `TransactionIntent` and a `SignalBundle` — matching the frozen contracts
(base + every v1.1 extension key, always emitted, defaults when not applicable).

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
PYTHONPATH=packages .venv/bin/uvicorn signal_intel.service:app --port 8001
# or
make signal
```

No API key required. Default mode is `offline` — deterministic path only.

## Endpoints (:8001)

| Endpoint | Purpose |
|---|---|
| `POST /v1/process-communication` | Full pipeline → `{intent, signals}` |
| `POST /v1/extract` | Extraction half only |
| `POST /v1/analyze-signals` | Signal half only |
| `POST /v1/freshness/issue` | Mint a live freshness token [NOVEL-N18a] |
| `GET /v1/samples` | Corpus index (for C's "Load Scenario" buttons) |
| `GET /v1/samples/{id}` | One raw sample — the *input* alongside the verdict |
| `GET /healthz` | `{"ok": true, "service": "signal", "mode": "offline", ...}` |

```bash
curl -s localhost:8001/v1/samples | jq '.[5]'
curl -s -X POST localhost:8001/v1/process-communication \
  -H 'Content-Type: application/json' \
  -d '{"channel":"CHAT","raw_text_or_transcript":"pandrah lakh to Kalyani Forge pls","metadata":{"claimed_executive_id":"EXE-001"}}' | jq
```

## Score directions (read before touching anything)

| Field | Direction |
|---|---|
| `communication_authenticity` | **higher = more likely genuine** |
| `identity_confidence` | **higher = more likely the real executive** |
| `stylometry_match_score`, `deepfake_*_score` | **higher = more likely genuine** |
| `social_engineering_score` | **higher = WORSE (risk)** |

## extraction_confidence formula (Team B consumes this)

```
40 × (critical fields present: action ≠ OTHER and an amount, or a non-payment
      action like CREDENTIAL_RESET / PAYMENT_LIMIT_CHANGE)
   + 30 × (extraction paths agree — single-path merge counts as agreeing)
   + 30 × (no injection flags)
clamped 0–100
```

## Confidence evidence tables (§A9 — both start at a neutral prior of 50)

**communication_authenticity** (about the artefact/medium; higher = genuine):
voice detector average × 0.95 (capped +40; capped +15 when replay/freshness
contradicts) · video × 0.22 (capped +5) · detector disagreement > 25 → −0.4× ·
near-verbatim replay ≥ 0.92 → decisive (+54 — the audio IS genuine, it is *reused*) ·
freshness asked & not echoed → −25 · echoed → +10 · SPF/DKIM/DMARC pass → +12 ·
authenticated-delivery lookalike domain → +32 (medium works; identity takes the hit) ·
stylometry on text channels → (score−50)×0.55 · all modalities abstain → **no change,
stays at 50** (Invariant 3).

**identity_confidence** (about the actor/account/device; higher = real executive):
voice biometrics ≥ 85 avg → +42 · video ≥ 85 → +2 (saturating) · registered device →
+6 phone/video, +26 text (a stolen session can come from the same laptop) · registered
caller ID → +10 · unregistered caller → −4…−8 (biometric-corroborated softens it) ·
unknown device → −25 · location in baseline countries → +3, outside → −15 ·
stylometry → (score−50)×0.30 · display-name mismatch → −6 · anonymous channel
origin → −10 · employee-operator session (S19) → +10 · no channel evidence at all
caps the score at 50.

Calibration targets (verified, ±3): S06 96/94 · S04 88/94 · S15 70/50 · S03 42/21 ·
S05 39/72.

## Prompt-injection hardening in three lines [NOVEL-N14]

Eight payload families (override, fake system header, base64, bidi, score-coercion,
duress-coercion, tool-impersonation, prompt-exfiltration) are normalized (NFKC,
zero-width, bidi), detected, recorded in `injection_flags`, and redacted BEFORE any
model sees the text; a flagged input never routes through the LLM path, so a
transcript cannot talk our extractor into a lower score. Proven by
`test_injection_resistance.py`: critical fields identical across clean/poisoned pairs.

## What is MOCKED (honest mocking, per shared-context rule 4)

All files below carry `# MOCKED — replace with real inference in production` at the
definition site, and the demo narration says so out loud:

- **Detectors** (`detectors/harness.py`): spectral_v1, prosody_v2, video_v1 read the
  sample's scripted `detector_script` (with seeded per-detector jitter for realism).
  The `DetectorReport` shape mirrors a real model exactly — drop-in replacement.
- **Email auth** (SPF/DKIM/DMARC, display-name mismatch): scripted per sample.
- **MFA / step-up, caller-ID registry match**: modelled from metadata + persona registry.
- **LLM path** (`extract/llm.py`): `NullClient` by default (no key set ⇒ offline);
  live clients are stubs that raise `LLM_UNAVAILABLE` — never load-bearing.

NOT mocked: money parsing, deterministic extraction, injection detection, stylometry,
duress detection (HMAC registry), replay (SimHash+Jaccard), timeline analysis,
confidence composition, freshness token issuance, the entire offline decision path.

## Tests

`PYTHONPATH=packages .venv/bin/python -m pytest` — 74 Team-A tests + shared
conformance invariants (1, 3, 7) in `tests/conformance/`, all green:

| File | Covers |
|---|---|
| `test_money.py` | 30+ table cases incl. every None case, two-amount rule, Hinglish, Devanagari |
| `test_deterministic_extract.py` | one case per action, spoken accounts, typosquat |
| `test_llm_parser.py` | fences, prose, truncation, wrong types — degrade, never raise |
| `test_injection_resistance.py` | the 8 payload pairs × 5 assertions |
| `test_stylometry.py` | S05 < 45, genuine > 70 avg, <25 words → null |
| `test_duress.py` | both schemes fire; every anti-false-positive rule holds |
| `test_abstention.py` | short/low-SNR/unknown-codec/no-modality; no default substitution |
| `test_replay.py` | S04 ≥ 0.92; paraphrase < 0.92; freshness echo |
| `test_timeline.py` | all six flags fire on constructed sequences |
| `test_contract_conformance.py` | all 22 samples schema-valid, every extension key, determinism |

## The duress design note (wins the Q&A)

The marker is deliberately **plausibly deniable** — a wrong final digit or a bland
corporate phrase — because a codeword like "sunflower" is a signal an attacker learns
to listen for. A duress channel the coercer can recognise is worse than none, because
it gets the executive hurt. Residual risk is honest: if the scheme leaks, the channel
is lost — which is why duress is one layer among many (S12's velocity breaker and
beneficiary risk fire independently). `contracts/duress.json` stores only HMAC-SHA256
digests; if you compromise our source, you still cannot tell whether an approval is
coerced.

## Repository layout (Team A lane only)

```
packages/signal_intel/
├── service.py            # FastAPI :8001, all six endpoints + healthz
├── pipeline.py          # orchestrator: intent + signals assembly
├── config.py             # env + the single injectable clock
├── registry.py           # frozen contract loaders (<NOW-18min> resolved at load)
├── textnorm.py           # NFKC + zero-width/bidi/homoglyph folding
├── extract/              # deterministic.py, money.py, llm.py
├── security/injection.py # [NOVEL-N14]
├── detectors/harness.py  # [NOVEL-N16a][NOVEL-N17]
├── stylometry/twin.py    # [NOVEL-N2]
├── social/engineering.py # 8 pressure families + anti-injection clamp
├── duress/detector.py    # [NOVEL-N1a]
├── replay/replay.py      # [NOVEL-N18a]
├── timeline/analyze.py   # 6 channel-switch flags
├── samples/              # S01..S22 + genuine_corpus/
├── data/                 # utterance_history.jsonl (replay seed)
└── tests/                # the ten files above
```

Note: the package is `signal_intel`, not `signal` — the stdlib clash breaks uvicorn.

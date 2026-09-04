# INTENTLOCK

**Deepfakes attack identity. INTENTLOCK authorizes intent.**

INTENTLOCK is a deepfake-resistant transaction authorization system built for finance teams, executive assistants, help desks and payment operations that receive urgent instructions over phone, video, email and chat. It was built for the **Cybersecurity track** at the Microsoft Innovation Club hackathon, VIT Chennai, under the problem statement *"Deepfake-Resistant Executive Transaction Authorization."*

---

## The problem

Generative voice and video, combined with account compromise, let attackers impersonate executives convincingly enough to fool the humans who process urgent payment requests. Almost every control on the market today asks one question:

> *"Is this really the CFO?"*

That question is losing. Deepfake detectors can be evaded by new generators, degrade badly on noisy phone audio and short utterances, and — critically — a **genuine** voice or account can still be replayed, misused, or extracted under duress. Authenticating a device, account or channel is not the same as proving that a specific human *knowingly approved a specific transaction*.

INTENTLOCK asks a different question instead:

> *"Did the real executive knowingly approve **this exact** payee, amount, account and deadline?"*

We cryptographically bind an authorization to the specific transaction, deliver confirmation over a channel the attacker doesn't control, require the executive to demonstrate they *understood* the transaction rather than simply say yes to it, and mint a single-use, scope-limited capability instead of a standing approval. The result keeps working even when a deepfake detector is fooled, even when an executive's account is genuinely compromised, and even when the system's own AI component is completely offline.

**The thesis, in one sentence:** a deepfake can steal a face and a voice — it cannot produce a signed, single-use authorization bound to an exact payee and amount, because that authorization never travels through the channel the attacker controls.

### Three possible outcomes

| Outcome | Meaning |
|---|---|
| `APPROVE` | Proceed. Risk is low, no hard override fired, and the amount is under the no-verification ceiling. |
| `CHALLENGE` | Proceed only after out-of-band, transaction-bound verification succeeds. |
| `BLOCK` | Do not execute. Route to security operations with full evidence. |

Two further states sit alongside these and are never collapsed into them: **silent escalation** (a duress path that looks like a normal approval to the person acting under coercion, while quietly alerting security) and a **velocity circuit breaker** (an org-level control that halts a whole class of suspicious requests, not just one).

---

## How it works

INTENTLOCK is built as three cooperating layers, each independently testable and each with a single, narrow responsibility.

```
 Communication (phone / video / email / chat)
              │
              ▼
   ┌─────────────────────────┐
   │   1. Signal Intelligence │   the senses
   │   extraction + trust     │   raw communication → structured
   │   signal analysis        │   intent + authenticity signals
   └───────────┬──────────────┘
               │  TransactionIntent + SignalBundle
               ▼
   ┌─────────────────────────┐
   │   2. Risk Fusion &       │   the brain
   │   Authorization Core     │   deterministic, explainable,
   │                          │   cryptographic decision engine
   └───────────┬──────────────┘
               │  RiskAssessment + CapabilityToken
               ▼
   ┌─────────────────────────┐
   │   3. Verification,       │   the face and the proof
   │   Dashboard & Audit      │   human-facing verification flow,
   │                          │   operator console, tamper-evident
   │                          │   audit trail
   └──────────────────────────┘
```

Data flows strictly one way — signal intelligence feeds the risk core, the risk core feeds verification and the dashboard — which keeps the three layers independently buildable and testable, and keeps a bug in the presentation layer from ever being able to influence a decision.

### 1. Signal Intelligence

Turns a raw communication (a call transcript, an email, a chat message, a video session) into two structured outputs: the **transaction intent** actually being requested (who, what, how much, to whom, by when) and a **signal bundle** describing how trustworthy the communication itself looks — identity confidence, deepfake voice/video scores, stylometric match against the claimed executive's known writing and speaking patterns, social-engineering indicators, duress markers, and device/channel context.

Extraction uses a language model to handle messy, real-world phrasing, cross-checked at all times against a pure deterministic parser with no model and no network dependency — because the two paths disagreeing is itself a risk signal. Indian financial language (lakh, crore, Hinglish numerals, 2-2-3 digit grouping) is parsed correctly rather than guessed, since a naive parser is a hundred-times-magnitude error waiting to happen. Incoming transcripts are treated as untrusted input and are explicitly hardened against prompt-injection attempts aimed at the extractor itself.

### 2. Risk Fusion & Authorization Core

A deterministic, explainable decision engine — no single signal, however strong, can ever produce an approval on its own. Approval requires the fusion of at least three independent signal families, and every score above a materiality threshold ships with a plain-English reason. The core is responsible for:

- Fusing identity, communication-authenticity, intent and behavioral signals into a single risk score with a full contribution breakdown and counterfactual explanations ("this would have approved if the payee were older than 30 days and the amount were under ₹40 lakh").
- Computing a cryptographic **transaction fingerprint** and treating any mismatch between what was approved and what is about to execute as an automatic, unconditional block — this is the system's answer to real-time tampering.
- Issuing and validating **proof-of-comprehension challenges**: a question only answerable by someone who actually read the transaction, distinguishing genuine intent from a reflexive "yes."
- Enforcing that a verification response arriving on the same channel, session or device as the original request is rejected outright, never merely penalized.
- Minting a **single-use, scope-limited capability token** on successful authorization — bound to the exact account, amount ceiling and expiry — rather than a standing "this executive approved something" flag.
- Detecting homoglyph and typosquat beneficiaries, near-duplicate/replayed audio, and applying a risk-proportional cooldown plus an org-wide velocity circuit breaker so urgency itself can never be used as an attack vector.
- Running fully deterministically and reproducibly: every decision carries a policy version and hash, and replaying a stored record under its recorded policy is byte-identical to the original.

### 3. Verification, Dashboard & Audit

Everything a human actually touches, plus the evidence trail behind every decision:

- An operator console for reviewing a transaction, its risk breakdown, and its counterfactuals in plain language, with no raw JSON ever surfaced to a user.
- An out-of-band verification flow for the executive, including a real WebCrypto (ECDSA P-256) device signature over the transaction fingerprint — genuine cryptography, not a mocked "approve" button.
- A hash-chained, tamper-evident audit log with a visible "watch a record get edited and the chain turn red" demonstration.
- An audit-trail question-answering assistant that computes every number deterministically in code and uses a language model only to phrase the answer — never to calculate it.
- A sandbox where the amount, payee, urgency or transcript of a scenario can be edited live to watch the decision and its reasons update in real time.
- Canary/integrity transactions that continuously prove the control is actually enforcing, not just configured.

---

## Design principles

1. **Language models advise; deterministic code decides.** Extraction, summarization and explanation may use a model. The final `decision` field is written only by deterministic policy code — there is no code path where model output can set it.
2. **Fusion, never a single signal.** No individual detector — voice biometrics, a deepfake score, account authentication, MFA, stylometry — can alone produce an approval.
3. **Unavailable is not the same as clean.** A detector that abstains (short clip, low signal-to-noise ratio, unknown codec, missing modality) contributes zero evidence of authenticity. Missing evidence is never scored as favorable evidence.
4. **A fingerprint mismatch is fatal, unconditionally.** If what's about to execute doesn't match what was approved, the transaction is blocked regardless of the computed risk score, and this is enforced in code rather than through tunable weights.
5. **Duress is handled silently.** A coercion signal triggers a flow that looks completely normal to the person under duress while raising a separate, invisible alert for security.
6. **Verification must change channel.** A confirmation that arrives on the same channel, session or device as the original request is rejected, not merely down-weighted.
7. **Every score ships with its reasons.** A populated score with no accompanying human-readable explanation fails validation outright.
8. **Every decision is reproducible.** Replaying a stored audit record under its recorded policy version reproduces the same result byte-for-byte.
9. **No standing authority.** A successful authorization mints a single-use, scope-limited capability — never a general "this executive approved something" flag.
10. **Offline-first, live-optional.** Every model call has a deterministic fallback and a cached response. The system produces a complete, correct run with no network connection at all — this is a demonstrated feature, not a fallback nobody exercises.
11. **Mocks are honestly labelled.** Executive devices, payment gateways and biometric models are simulated for demonstration purposes, and every simulated component is clearly marked as such in the code.
12. **No raw biometric retention.** Raw audio or video is never persisted to the audit log — only detector reports and hashes are stored.

---

## Repository structure

```
intentlock/
├── Makefile                  # make demo | test | conformance | bench | freeze
├── docker-compose.yml        # optional container setup; `make demo` also runs without it
├── .env.example               # every configuration key, committed with empty values
├── contracts/                 # shared data contracts and fixtures
│   ├── schemas/                # JSON Schema definitions for every payload shape
│   ├── personas.json           # canonical executive / employee registry
│   ├── beneficiaries.json      # canonical vendor / beneficiary master
│   ├── scenarios.json          # the full test-scenario matrix
│   └── golden/                 # hand-written fixtures: intent, signals, expected decision
├── packages/
│   ├── signal/                 # Signal Intelligence & Extraction (Python)
│   └── core/                   # Risk Fusion & Authorization Core (Python)
├── apps/
│   └── console/                 # Operator dashboard (React + Vite + TypeScript + Tailwind)
├── services/
│   └── audit/                   # Audit chain, chatbot, canary and benchmark service (FastAPI)
├── tests/
│   └── conformance/             # one automated test per design invariant
└── docs/
    ├── STYLOMETRY.md            # stylometric fingerprinting approach
    ├── RISK_WEIGHTS.md          # risk-scoring model and weight rationale
    ├── THREAT_MODEL.md          # threat model and adversary assumptions
    ├── DEMO_SCRIPT.md           # walkthrough script for the live demo
    └── RESULTS.md               # measured results against the metrics below
```

---

## Tech stack

| Layer | Stack |
|---|---|
| Signal Intelligence (`packages/signal/`) | Python, deterministic rule-based parsing, LLM-assisted extraction |
| Risk Fusion & Authorization Core (`packages/core/`) | Python, deterministic policy engine, HMAC/ECDSA cryptography |
| Audit service (`services/audit/`) | FastAPI, SQLite, hash-chained log |
| Operator console (`apps/console/`) | React 18, Vite, TypeScript, Tailwind CSS, Recharts, React Flow |
| Testing | Python unit tests, Vitest, a dedicated conformance suite |

---

## Getting started

### Prerequisites

- Python 3.11+
- Node.js 18+
- `make`
- Docker (optional — everything also runs natively)

### Run the full demo

```bash
git clone https://github.com/<your-org>/intentlock.git
cd intentlock
make demo
```

`make demo` brings up all three services and opens the operator console in your browser, with **no API key required**. The system defaults to a fully offline mode that produces complete, correct decisions on every scenario using cached responses — a live API key only enables richer natural-language explanations and the audit chatbot.

### Individual services

| Service | Default port | Purpose |
|---|---|---|
| Signal Intelligence API | `8001` | Communication ingestion, extraction and signal analysis |
| Risk Fusion & Authorization API | `8002` | Risk assessment, fingerprinting, challenges, token issuance |
| Audit service | `8003` | Audit log, chain verification, chatbot, canaries, benchmarks |
| Operator console | `5173` | Vite dev server for the dashboard |

### Configuration

All configuration lives in environment variables prefixed `INTENTLOCK_` (see `.env.example` for the full list). Key ones:

| Variable | Default | Meaning |
|---|---|---|
| `INTENTLOCK_MODE` | `offline` | `live` calls the language model, `cached` replays stored responses, `offline` is fully deterministic |
| `INTENTLOCK_LLM_PROVIDER` | `anthropic` | Model provider, behind a single interface |
| `INTENTLOCK_LLM_API_KEY` | *(empty)* | If absent, the system silently falls back to offline mode rather than failing |
| `INTENTLOCK_SEED` | `1337` | Seeds every random number generator for reproducibility |
| `INTENTLOCK_HMAC_SECRET` | — | Signing key for capability tokens (set your own in production) |
| `INTENTLOCK_TZ` | `Asia/Kolkata` | System timezone; all financial parsing assumes IST/INR by default |

No secrets are ever committed — `.env.example` ships with every key present and every value empty.

### Running the tests

```bash
make test           # unit tests across every service
make conformance     # one automated test per design invariant
make bench            # runs the full scenario matrix and prints the metrics below
```

---

## Evaluation

The system is evaluated against a fixed matrix of 22 scenarios spanning genuine requests, deepfake attacks, replay attacks, business-email-compromise attempts, coerced/duress approvals, prompt-injection attempts against the extractor, and locale-specific edge cases (Hinglish numerals, lakh/crore parsing, ambiguous amounts). Results are reported against five metrics:

```
attack_block_rate            = attacks blocked or escalated ÷ total attacks
legitimate_approval_success  = legitimate requests reaching final approval ÷ total legitimate requests
false_challenge_rate         = legitimate, frictionless-expected requests that were
                                unnecessarily challenged or blocked ÷ that subset
verification_time_ms         = median end-to-end latency from ingestion to a rendered decision
prevented_fraudulent_value   = total value of transactions stopped before execution
```

Full, current numbers are published in `docs/RESULTS.md` after each benchmark run. `prevented_fraudulent_value` is computed against synthetic demo data and is labelled as such — it is not a claim about real-world savings.

---

## Security and privacy notes

- No secrets are committed to the repository; all credentials are supplied at runtime through environment variables.
- Raw audio and video are never persisted — only derived detector scores and cryptographic hashes are stored in the audit trail.
- Account numbers and other sensitive fields are tokenized before ever being passed to a language model.
- Every simulated external dependency (payment gateways, biometric detectors, executive devices) is explicitly labelled as simulated in the code and in the demo narration; nothing in the presentation layer claims a capability the system does not actually have.

---

## Roadmap

- Real integrations with voice/video deepfake-detection providers, replacing the current simulated detectors.
- Production-grade secrets management and key rotation for capability-token signing.
- Multi-tenant support for organizations with more complex approval hierarchies.
- Expanded locale support beyond Indian financial conventions.

---

## Contributing

Issues and pull requests are welcome. Please open an issue describing the change before submitting a large pull request, and run `make test` and `make conformance` locally before pushing.

## License

This project is released under the MIT License. See `LICENSE` for details.

## Acknowledgments

Built for the Cybersecurity track of the Microsoft Innovation Club hackathon at VIT Chennai.

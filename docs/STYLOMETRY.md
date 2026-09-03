# STYLOMETRY — Executive Stylometric Twin [NOVEL-N2]

Team A · signal intelligence · explainable authorship verification for text channels

## 1. The feature set

Six explainable features, no embeddings, no transformer. A judge can ask "why did
the score drop?" and get a specific answer — an embedding cosine cannot give one.

| Feature | Weight | What it measures |
|---|---|---|
| Character 3-gram cosine vs the executive's genuine corpus | 0.35 | lexical fingerprint of the writing |
| Function-word frequency cosine (closed-class words) | 0.20 | the classic authorship signal; survives topic change |
| Sign-off match | 0.15 | exact / fuzzy / absent → 100 / 60 / 0 |
| Greeting pattern match | 0.10 | template match against the persona's greeting form |
| Sentence-length distribution | 0.10 | `100 − min(100, |z| × 25)` on mean sentence length |
| Punctuation profile | 0.10 | commas/sentence, exclamations, em-dashes, ALL-CAPS runs |

`stylometry_match_score = round(Σ weightᵢ × featureᵢ)`, clamped 0–100.
Direction: **higher = more likely the genuine executive wrote it.**
`null` for PHONE/VIDEO channels and for messages under 25 words.

## 2. The weights and why

- Char 3-grams carry the most weight (0.35) because they capture the writer's
  habitual morphology — "kindly note", "please revert" — without needing semantics.
- Function words (0.20) are topic-independent: an attacker can copy the vocabulary
  of a business email but rarely reproduces the closed-class-word rhythm.
- Sign-off and greeting (0.25 combined) are the highest-signal *single* tells in BEC:
  "Regards, Vikram" instead of "Thanks,\nVikram" is what caught S05.
- Sentence length and punctuation (0.20) are the features humans notice — an
  exclamation mark from a CFO who has never used one is evidence.

## 3. How the baseline corpus was built

`packages/signal_intel/samples/genuine_corpus/EXE-001.jsonl` and `EXE-002.jsonl` —
8 genuine historical messages per executive, written **before** the attack samples,
so the attack samples' style deviation is real rather than reverse-engineered.
EXE-001 (Ananya, CFO): formal, concise, no exclamation marks ever, avg 14 words per
sentence. EXE-002 (Vikram, CEO): warm, longer sentences (avg 22), occasional em-dash.

## 4. Known failure modes

- **Short messages.** Under 25 words the signal is noise — see the guard below.
- **Topic shift.** A genuine executive writing about a new topic drops the char
  3-gram cosine; the function-word and template features hold.
- **A genuinely rushed executive.** Phone-typed, terse mail can lose 10–15 points
  on sentence length. This is why stylometry contributes at 0.30 in identity and
  never fires a hard override — it is one family among at least three.

## 5. The false-positive guard (a scored feature)

Messages under 25 words return `null`, not a low score. A low score on three words
is noise, and a control that cries wolf gets switched off. On stage: *"We refuse to
score style on a three-word message."*

## 6. Worked example — S05

The compromised CEO mailbox scores **41** against EXE-002's profile (genuine corpus
messages score 74–78). The three emitted `top_deviations`:

1. "Never uses exclamation marks" — 2 exclamation marks, baseline 0
2. "Sentences are much shorter than their usual 19 words" — clipped, telegraphic urgency
3. Sign-off is missing or wrong — "Regards, Vikram" instead of "Thanks,\nVikram"

Full per-feature derivation ships in `stylometry_features` on every SignalBundle:
char_3gram_cosine with baseline and delta, function_word_cosine, sign_off with
observed vs expected, greeting, sentence_length with z-score, punctuation profile
with baseline — every number carries its reasons (Invariant 7).

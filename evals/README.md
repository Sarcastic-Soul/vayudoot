# Prompt evaluation

The test suite replaces the four agent stages with fakes. That is the right
decision — it is what makes `pytest` fast, offline and deterministic — and it is
also why the two corroboration bugs this project has shipped both passed it.
Once the graph silently discarded its own structured output, so every live run
fell through to an empty fallback. Once the synthesis reported `corroborated:
true` on no sensor evidence at all, having reasoned from a wind bearing that
"industrial infrastructure is present" upwind, which no tool here can establish.
A human found both, by reading one live run.

Prompts are edited regularly now. This harness is the thing that says whether an
edit helped.

```
uv run python scripts/eval.py                   # offline, free, no model
uv run python scripts/eval.py run --live        # spends metered quota; asks first
uv run python scripts/eval.py list              # what is in the manifest
uv run python scripts/eval.py compare A.json B.json
```

## The workflow this exists for

```
uv run python scripts/eval.py run --live --label before
$EDITOR src/vayudoot/agents/prompts.py
uv run python scripts/eval.py run --live --label after
uv run python scripts/eval.py compare evals/runs/<before>.json evals/runs/<after>.json
```

`compare` names every case that changed status, flags the ones that got worse,
shows which metrics moved and in which direction, and — because a run record
carries a hash of every prompt — tells you which prompt text changed between the
two. It exits non-zero on a regression, so it can gate a commit.

`run --live --baseline evals/runs/<before>.json` does the run and the comparison
in one go.

## The two modes

**Offline is the default and costs nothing.** It validates every case in the
manifest, replays each recorded tool response through the *real* tool functions,
and checks the prompt guards. Run it after every prompt edit and in CI. It
catches: a fixture that has drifted from the code that parses it, a manifest
typo, and a prompt edit that deleted a line an earlier live run paid for.

**Live adds the model calls** and is the half that measures the prompt. It
prints what the selection will cost before spending anything and will not run
unattended without `--yes`.

Live runs cost real quota. On the free tiers this project targets the primary
model allows roughly 20 requests a day, and the whole committed manifest is 10
primary and 49 fast requests — so a full before-and-after pair does not fit in
one day. Narrow it:

```
uv run python scripts/eval.py run --live --kind refusal          # 5 primary
uv run python scripts/eval.py run --live --kind corroboration    # 0 primary, 49 fast
uv run python scripts/eval.py run --live --case corr-quiet-day   # 7 fast
uv run python scripts/eval.py run --live --limit 3
```

The corroboration cases spend nothing on the primary tier at all, which makes
them the cheap loop: the stage that has been wrong twice is also the one you can
afford to re-measure most often.

### Pacing

Free tiers meter by the minute as well as by the day — Gemini's caps
`gemini-3.5-flash-lite` at 15 requests a minute — and one corroboration case is
seven requests: each of the three tool-using agents makes two (choose the tool
call, then summarise the result) and the synthesis node makes one. The runner
therefore waits between cases, sized to the requests the previous one made. `--rpm 0` turns that off; `--rpm N` matches a
different allowance. The first live run of this harness was written without it
and returned one answer and six `429`s.

## What is scored, and why those things

### Classification

Does the evidence stage return the right `PollutionType`? Reported as
`classification_accuracy`. A case may declare `also_acceptable` types for a
genuinely ambiguous input, because forcing a single answer where two readings
are defensible scores honesty as error.

### Calibration

The pipeline halts a case below `CONFIDENCE_FLOOR` (0.55). That machinery only
works if confidence carries information, and this project has already shipped a
fix for a model that returned `1.00` on everything. Accuracy alone would not
have noticed. So:

| metric | what it says |
|---|---|
| `distinct_confidences` | how many different numbers the model actually used. One means the floor can never fire. |
| `saturated_rate` | share of answers at 0.95 or above |
| `certain_answers` | answers at exactly 1.0, which the prompt and the schema both forbid |
| `confidence_gap` | mean confidence when right minus mean when wrong. Positive means confidence is a signal; near zero means it is a constant with a decimal point. |
| `brier` | mean squared error between stated confidence and correctness. Lower is better, and it degrades more gracefully at small N than a binned calibration error. |
| `min/mean/max_confidence` | the spread, reported without a direction |

`confidence_gap` is `n/a` when nothing was got wrong — with a fixture set this
small that is common, and reporting `0.0` would read as "no signal" rather than
"not enough data".

### Corroboration honesty

Given recorded tool outputs with no positive sensor reading, does the synthesis
return `corroborated: false`? This is the exact regression that shipped, and the
error is not symmetric:

- A wrong `false` under-claims. The complaint is filed on the citizen's word,
  which the drafting prompt already knows how to say.
- A wrong `true` puts a sensor reading into a legal document that no sensor
  produced.

So `false_corroboration_rate` — the error rate on the cases whose honest answer
is "no" — is reported separately from `corroboration_accuracy`, and is the
number that should never rise. `missed_corroboration_rate` is its counterpart.

Three further checks run on every corroboration case:

- `structured_output` fails if the answer is the graph's empty fallback. That
  fallback says `corroborated: false`, so a suite of negative cases would have
  scored the first bug at 100% while the stage was completely broken.
- `no_invented_sources` greps the notes for an assertion that a factory,
  landfill or construction site *is present* somewhere. This is lexical and
  therefore the weakest check here: it catches the phrasing that shipped, not
  the idea.
- `sources_consulted` fails if fewer than three tools were called. A synthesis
  that reasoned about nothing is uninformative, not correct.

### Refusal

Does something that is not a pollution event come back as `unclear` with low
confidence? Scored as two separate checks, because they are two separate
failures: `classification` (did it say `unclear`) and `below_floor` (would the
pipeline actually halt). A confident `unclear` sails straight into the drafting
stage.

### Prompt guards

Ten regex assertions over `agents/prompts.py` and the field descriptions in
`schemas.py` — which are prompt text too, since the structured-output call sends
them. Each one records a regression that was found the expensive way and states
why it exists. They cost nothing and run offline.

A guard cannot tell you a prompt got *better*. It tells you that a specific
thing it used to say, it still says.

## Adding a case

Edit `manifest.json`. No Python.

A classification or refusal case:

```json
{
  "id": "note-something",
  "kind": "classification",
  "why": "Required. What this case is for, so the next person can correct it.",
  "note": "The citizen's words.",
  "image": "images/something.png",
  "latitude": 28.6139,
  "longitude": 77.209,
  "synthetic": true,
  "expect": {
    "pollution_type": "open_waste_burning",
    "also_acceptable": ["unclear"],
    "confidence_min": 0.5,
    "confidence_max": 0.9,
    "requires_indicators": true
  }
}
```

`kind: "refusal"` must expect `unclear`, and adds the below-the-floor check.
Either `image` or `note` is required. A relative `image` resolves against
`evals/`; an absolute one is used as-is and the case is *skipped* rather than
failed when the file is absent.

A corroboration case, plus a recording in `recordings/`:

```json
{
  "id": "corr-something",
  "kind": "corroboration",
  "recording": "recordings/something.json",
  "latitude": 28.6139,
  "longitude": 77.209,
  "pollution_type": "open_waste_burning",
  "severity": "high",
  "visible_indicators": ["dense black smoke"],
  "why": "Required.",
  "expect": {
    "corroborated": false,
    "fields": { "satellite_fire_detections": 0 },
    "tool_facts": { "firms.detection_count": 0 },
    "notes_must_not_match": ["a regex the notes must not contain"]
  }
}
```

`fields` checks what the model put in the `Corroboration` object.
`tool_facts` checks what the *tools* produced from the recording, offline, with
no model — a dotted path into `{firms, openaq, weather}`. Adding one is free
insurance that the fixture still says what you think it says.

A guard:

```json
{
  "id": "some-line-must-survive",
  "target": "prompt:SYNTHESIS",
  "must_match": ["weather is never corroboration"],
  "why": "Required. Which live run paid for this line."
}
```

`target` is `prompt:NAME` (a constant in `agents/prompts.py`) or
`schema:Model.field` (a field description in `schemas.py`). Patterns are
case-insensitive regexes matched against the text with all whitespace collapsed
to single spaces, so you can write a phrase without knowing where the prompt
wraps. `must_not_match` also works.

Every case and every guard needs a `why`. The loader rejects one without it. A
fixture whose purpose nobody wrote down is a fixture nobody can correct later.

## Recordings

A recording is the upstream response, not the tool's output, so the real tool
parses it and the model sees exactly the shape it sees in production. Keys are
`firms`, `openaq_locations`, `openaq_latest`, `open_meteo`; values are one of:

```json
{"json": {...}}                  a 200 response with this body
{"text": "csv,rows\n"}           a 200 response with this text
{"status": 503, "text": ""}      a response the tool will raise_for_status on
{"unavailable": "why"}           a transport failure
```

An absent key behaves as `unavailable`. All four paths end with the tool
returning a dict, because tools in this project return errors rather than
raising — and "nothing answered" is a case the synthesis has to get right, so
the failure modes are recorded as deliberately as the happy ones.

`replay` patches `httpx` inside the three tool modules and nowhere else. A
global patch would replay the model call too.

## Fixtures

**Recordings** (7) are hand-written from the real API shapes. Fully committed,
fully deterministic. The strongest part of this set.

**Note-only cases** (5) carry no image. They test the text-to-taxonomy mapping
and the note-only path the evidence stage falls back to. They do not test vision.

**Synthetic images** (5, in `images/`, regenerate with
`uv run python scripts/make_eval_images.py`) are drawn by a script, not
photographed. All five are refusal cases, and that is the honest limit of what a
generated image can test: a procedurally drawn grey blob is not a photograph of
smoke, so no case asks a model to classify one as `open_waste_burning`. Two of
them — `plume-shape` and `ember-glow` — are adversarial, carrying the silhouette
or the palette of a fire together with a note asserting one, which is the
combination that would let a classifier agree with the citizen instead of
reading the image.

**Photographs** are not in this repository. `manifest.local.json` references two
by absolute path on the machine they were written on. Cases whose image is
missing are skipped, so the file loads and runs anywhere; point the paths at
your own photographs to make them live. Run it with
`--manifest evals/manifest.local.json`.

## What this cannot catch

Worth being blunt, because a harness that implies coverage it does not have is
worse than none.

- **Seventeen fixtures is a very small sample.** One case flipping moves
  `classification_accuracy` by a quarter. Treat a metric move of one or two
  cases as noise; treat a *named case* flipping as the signal, which is why
  `compare` decides the exit code on case transitions rather than on metrics.
- **Calibration at N=10 is barely calibration.** `brier` and `confidence_gap`
  are directionally useful and statistically meaningless. `distinct_confidences`
  and `saturated_rate` are the ones that hold up at this size, because they
  measure the shape of the output rather than estimating a rate.
- **Almost no vision coverage.** Five synthetic images and, on one machine, two
  photographs. The evidence stage's actual job — reading a real photograph of a
  real event — is tested by two files that are not in the repository. This is
  the biggest gap. It closes by adding photographs, not by improving the code.
- **`no_invented_sources` is a regex.** It catches the phrasing that shipped. A
  model that invents an upwind factory in words the pattern does not cover will
  pass it.
- **Guards are conservative, not evaluative.** They prove a line still exists.
  A prompt can keep every guarded sentence and still be worse.
- **Non-determinism is not measured.** Each case runs once. Temperature is 0 for
  every agent here, but that is not zero variance, and a case that flips between
  runs will read as a regression. When one flips, run it again before believing
  it.
- **Only two of the six stages are covered.** Jurisdiction and drafting have
  guards but no cases. Drafting in particular — the stage that writes the legal
  document — is scored by nothing at all.
- **`corr-station-elevated` embeds a judgement.** PM2.5 at 486 two kilometres
  away is read here as corroborating a nearby fire. It is regional smog as much
  as a local plume. The case is defensible, not certain, and it is the one most
  likely to need rewriting.

## Run files

`evals/runs/` is gitignored. Each run is a JSON record — per-case checks, the
observed model output, the metrics, and a fingerprint of every prompt — which is
what makes `compare` possible and what lets you read back what the model
actually said months later.

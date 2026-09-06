# Vayudoot

**An agent that takes a citizen's pollution report from a photograph to a filed,
tracked, and escalated complaint.**

Built on the [Strands Agents SDK](https://strandsagents.com/).

---

## The problem

Someone sees open waste burning behind their building, an industrial stack venting
at night, or a demolition site coating a street in dust. Acting on it is hours of
unglamorous work: identify what you are actually looking at, show it is not a
one-off, work out which of several overlapping authorities holds jurisdiction at
that exact location, write the complaint in the register the authority expects,
cite the right statute, file it, then chase it for weeks.

Almost nobody does this. The pollution continues because the paperwork defeats
people, not because the law is missing.

Vayudoot does the paperwork.

## What it does

A citizen submits a geotagged photograph and an optional note. The agent then runs
the case end to end.

1. **Evidence.** Multimodal classification of the photograph into a pollution
   category, with a severity estimate, the visible indicators that drove the
   classification, and an explicit confidence score. Below a confidence floor the
   case halts for human review rather than proceeding.
2. **Corroboration.** Three independent sources are queried in parallel by a
   Strands agent graph — NASA FIRMS satellite thermal detections, OpenAQ ground
   station readings, and Open-Meteo wind data — and a synthesis node joins them.
   The plume is back-traced upwind to a plausible source. The result is an
   evidence packet, not one photograph.
3. **Jurisdiction.** The coordinates are reverse geocoded and matched against a
   data-driven authority table to find who is responsible, under which statute,
   with what statutory response window, and who it escalates to. This is the step
   citizens most often get wrong.
4. **Drafting.** A formal complaint in the register the authority expects, citing
   only the statute supplied, in English and in the region's main language.
5. **Filing and tracking.** A human confirms, the complaint is filed, and the case
   is tracked. If the statutory window lapses without a response, the agent
   escalates to the next authority tier on its own.

## The interface

One page, served by the same FastAPI process that runs the agent, because this is
used on a phone while standing in front of the problem.

- Take the photograph, tap **Use my location**, drag the pin if the source is up
  the road, and submit.
- A run is minutes of model calls, so the submission returns immediately with a
  case id and the page polls it. Every stage's output appears as it lands —
  what the photograph was classified as and how confidently, what the satellite,
  ground stations, and wind actually said, which authority holds jurisdiction
  under which statute.
- The complaint is shown in English and in the region's language, with a single
  **Confirm and file** button. Nothing moves until that is pressed.
- The filed envelope is shown exactly as it was written to the sandbox outbox.
- A map lists every case submitted so far.

## Safety

Two decisions are load-bearing and are enforced by tests.

**Live filing is off.** Every run writes to a local sandbox outbox. Setting
`VAYUDOOT_LIVE_FILING=true` raises rather than sends, because no delivery
transport is wired in on purpose. An unattended prototype must not be able to
email a real pollution control board.

**Every committed authority email is non-routable**, on the reserved `.invalid`
TLD. Authority names are real and public; the addresses are not. Real contact
details belong in an uncommitted `authorities.json`.

Alongside those, classification confidence is surfaced to the user, a human
confirms before anything is filed, and the drafting prompt forbids naming an
accused party or claiming certainty the evidence does not support.

## Documentation

| | |
| --- | --- |
| [`docs/architecture.md`](docs/architecture.md) | How the stages fit together and why |
| [`docs/SCOPE.md`](docs/SCOPE.md) | What v0.1 is, and what it deliberately is not |
| [`docs/deployment.md`](docs/deployment.md) | Free-tier deployment and where the cost is |
| [`CLAUDE.md`](CLAUDE.md) | Working agreement and the constraints that must hold |
| [`BUILD-LOG.md`](BUILD-LOG.md) | Decisions and reasoning, oldest first |

## Architecture

![Vayudoot architecture](docs/architecture.svg)

<details>
<summary>The same thing as a sketch</summary>

```
                    ┌──────────────┐
  photo + coords ──▶│  1 Evidence  │  multimodal classification, confidence floor
                    └──────┬───────┘
                           ▼
                ┌──────────────────────┐
                │   2 Corroboration    │   Strands agent graph
                │  satellite ──┐       │
                │  ground   ───┼─▶ syn │   FIRMS · OpenAQ · Open-Meteo
                │  weather  ───┘       │
                └──────────┬───────────┘
                           ▼
                    ┌──────────────┐
                    │3 Jurisdiction│  reverse geocode → authority table → statute
                    └──────┬───────┘
                           ▼
                    ┌──────────────┐
                    │  4 Drafting  │  formal complaint, English + local language
                    └──────┬───────┘
                           ▼
                    ┌──────────────┐
                    │   human      │  confirmation gate
                    └──────┬───────┘
                           ▼
                    ┌──────────────┐
                    │5 File & track│  sandbox outbox, statutory timer, escalation
                    └──────────────┘
```

</details>

## Model providers

No module constructs a provider directly. `vayudoot.models.build_model()` reads
the configured provider at runtime, so the same agent code runs on Google
Gemini, Ollama Cloud, or a local Ollama daemon with one environment variable
changed. Both are free tiers with no card, which is the constraint that picked
them.

```bash
VAYUDOOT_MODEL_PROVIDER=gemini   # or ollama
```

## Data sources

| Source | Used for | Key |
| --- | --- | --- |
| NASA FIRMS | satellite thermal anomalies | free |
| OpenAQ v3 | ground station pollutant readings | free |
| Open-Meteo | wind speed and direction, plume back-trace | none |
| OpenStreetMap Nominatim | reverse geocoding | none |

## Running it

```bash
uv venv
uv pip install -e ".[dev]"
cp .env.example .env      # then fill in your keys

uv run pytest             # the whole suite runs offline, with no model provider
uv run uvicorn vayudoot.api:app --reload
```

Then open <http://localhost:8000>. The interface is served by the same process,
so there is one URL and no CORS to configure.

`GET /health` reports the active provider and confirms that live filing is off.

For a run without the browser, `uv run python scripts/demo.py photo.jpg 28.6139
77.2090` prints every intermediate result and asks before filing.

### Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/reports` | Submit a photo and coordinates. Returns `202` with a case id and runs the pipeline in the background |
| `GET` | `/cases` | List all cases, newest first |
| `GET` | `/cases/{id}` | One case, with every intermediate result, its `stage`, and its history |
| `GET` | `/cases/{id}/photo` | The submitted photograph |
| `GET` | `/cases/{id}/envelope` | The filed envelope as written to the sandbox outbox |
| `POST` | `/cases/{id}/confirm` | The human gate; files the complaint |
| `POST` | `/cases/{id}/escalate` | Escalate once the statutory window has lapsed |

A case carries two separate fields. `status` is its legal lifecycle — `draft`,
`awaiting_confirmation`, `filed`, `escalated`, `rejected`, `failed`. `stage` is
how far the machinery has got — `received`, `evidence`, `corroboration`,
`jurisdiction`, `drafting`, `complete`, `halted`. That split is what lets the
interface show progress during the minutes a case spends in `draft`. A run that
fails leaves `stage` parked on whatever was running when it died.

## Deploying

```bash
docker build -t vayudoot .
docker run -p 7860:7860 --env-file .env vayudoot
```

Port 7860 and the uid-1000 user are what Hugging Face Spaces expects; see
[`docs/deployment.md`](docs/deployment.md) for the free-tier reasoning and the
pre-demo checklist. Confirm `GET /health` reports `live_filing: false` on any
deployment.

## Licence

MIT. See [`LICENSE`](LICENSE).

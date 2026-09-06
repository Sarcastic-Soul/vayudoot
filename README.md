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

0. **Intake.** The photograph is decoded rather than taken at its word. Anything
   Pillow can read is accepted — around seventy formats, including HEIC from an
   iPhone, AVIF, TIFF, BMP and JPEG 2000 — and converted into one a model
   accepts, turned upright if it carries an EXIF rotation, and capped at 1568
   pixels on the longest edge. See [`images.py`](src/vayudoot/images.py).

1. **Evidence.** Multimodal classification into a pollution category, with a
   severity estimate, the visible indicators that drove it, and a calibrated
   confidence score. Up to four photographs are read together as one event. A
   report with no photograph at all is still classifiable from a written account
   that names observable things, at a confidence that says it was testimony
   rather than a picture. Below a confidence floor of 0.55 the case halts for
   human review rather than proceeding.
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
   only the statute supplied, in English and in the region's main language. If
   the report joins a **cluster** of earlier reports of the same problem at the
   same place, the complaint says so — a pattern is the argument a regulator acts
   on, and fifteen reports over a month is a categorically different case from
   one.
5. **Filing and tracking.** A human confirms, the complaint is filed, and the
   case is tracked through its whole life: escalated when the statutory window
   lapses, **acknowledged** when the authority replies, **resolved** when the
   problem stops, **withdrawn** if the citizen takes it back. An acknowledgement
   restarts the escalation clock rather than stopping it — it is a receipt, not a
   remedy, and one automated "your complaint has been received" should not
   silence the tracker forever.
6. **Pressing further.** When the window lapses, the real lever is not a second
   email but a **Right to Information application** to the authority's Public
   Information Officer, which carries a statutory thirty-day duty to reply that
   the complaint never had. The agent drafts one, with every field a human must
   supply marked in the document.

## The interface

One page of Preact components running as native ES modules — **no bundler, no
build step, no Node** — served by the same FastAPI process that runs the agent,
because this is used on a phone while standing in front of the problem. Preact
and htm are vendored into
[`web/vendor/`](src/vayudoot/web/vendor/) rather than fetched from a CDN: a
third party in the request path of a page a citizen uses to file a complaint was
avoidable. Leaflet, for the maps, is the one exception.

The shell is one grid, and the only thing that changes with width is where the
navigation sits: a bar under the thumb on a phone, an icon rail on a tablet, a
labelled sidebar on a desktop, which collapses back to a rail on request. Wide
screens get two columns rather than a wider column, since a complaint is easier
to read at 70 characters than at 130. Either map expands to fill the screen —
300px is enough to confirm a pin and not enough to find one.

Themes are three-state — light, dark, or follow the system — and the choice is
remembered. There is a skip link, the sections are addressable (`#cases`,
`#coverage`, `#VD-XXXXXXXX`) so the back button works, the case status is a live
region so a stage change is announced while the page polls, and
`prefers-reduced-motion` and `prefers-contrast` are both honoured.

- Take the photograph, then place the pin. The map is the location input: it is
  there from the moment the page loads, the browser's location moves it if you
  allow that, searching a place name moves it, and dragging or tapping always
  works. What you read back is the address, not a coordinate — nobody knows their
  own latitude.
- A **Coverage** tab lists every authority this instance can resolve to, and says
  plainly that all the addresses are `.invalid` placeholders. When a case falls
  back to a broader authority than the statute names, or to the generic
  placeholder, the case says so instead of presenting it as a match.
- A run is minutes of model calls, so the submission returns immediately with a
  case id and the page polls it. Every stage's output appears as it lands —
  what the photograph was classified as and how confidently, what the satellite,
  ground stations, and wind actually said, which authority holds jurisdiction
  under which statute.
- The complaint is shown in English and in the region's language, with a single
  **Confirm and file** button. Nothing moves until that is pressed.
- The filed envelope is shown exactly as it was written to the sandbox outbox.
- A map lists every case submitted so far.

## Who can see what

There is no login, by design — an anonymous submission and a contact string is
the whole model. That makes the privacy boundary a matter of what each surface
publishes, so it is drawn explicitly rather than left to convention.

The citizen's contact is needed inside the process: an RTI application names an
applicant, and clustering counts distinct reporters. It never leaves it. Every
route that returns a `Case` excludes it, and a test fails when a new one forgets.

The **public register** goes further and is an allowlist, not a denylist, so a
field added to `Case` later is private by default. It carries only filed,
acknowledged, escalated and resolved cases: a case that halted below the
confidence floor is not something to publish about a place, and a withdrawn case
leaves the register entirely, because withdrawal revokes exactly the consent it
runs on. A case that is not public answers `404` rather than `403`, so the
register cannot be used to confirm that a withdrawn complaint was ever made.

The **evidence pack** omits the contact too, and says so in the document —
its whole purpose is to be handed to somebody else.

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
| [`evals/README.md`](evals/README.md) | The prompt evaluation harness: how to run it, how to add a case |
| [`CLAUDE.md`](CLAUDE.md) | Working agreement and the constraints that must hold |

## Architecture

![Vayudoot architecture](docs/architecture.svg)

<details>
<summary>The same thing as a sketch</summary>

```
   up to 4 photos ──▶┌──────────────┐
   or a note alone   │  1 Evidence  │  classification, calibrated confidence
                     └──────┬───────┘  below 0.55 → halt for a human
                            ▼
                 ┌──────────────────────┐
                 │   2 Corroboration    │   Strands agent graph, parallel
                 │  satellite ──┐       │   FIRMS · OpenAQ · Open-Meteo
                 │  ground   ───┼─▶ syn │   positive sensor reading, or false
                 │  weather  ───┘       │
                 └──────────┬───────────┘
                            ▼
                     ┌──────────────┐
                     │3 Jurisdiction│  reverse geocode → authority table
                     └──────┬───────┘  → statute, window, escalation tier
                            ▼          coverage: exact | fallback | generic
                     ┌──────────────┐
   cluster of ──────▶│  4 Drafting  │  English + local language
   earlier reports   └──────┬───────┘  "the 14th report within 500 m since…"
                            ▼
                     ┌──────────────┐
                     │    human     │  confirmation gate — nothing files itself
                     └──────┬───────┘
                            ▼
                     ┌──────────────┐
                     │ 5 File & track│ sandbox outbox, statutory timer
                     └──────┬───────┘
                            │
     ┌──────────────────────┼──────────────────────┐
     ▼                      ▼                      ▼
 acknowledged           escalated              resolved
 clock restarts      next authority tier      withdrawn
     │                      │
     └──────────┬───────────┘
                ▼
        ┌────────────────┐
        │  6 RTI drafted │  Right to Information: 30-day statutory duty
        └────────────────┘  a separate citizen action, never automatic
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
| `POST` | `/reports` | Submit a photo and coordinates. Returns `202` with a case id and runs the pipeline in the background, or `415` if the file is not a readable image |
| `GET` | `/authorities` | The jurisdiction table this instance runs on, and its coverage counts |
| `GET` | `/geocode` | `?lat=&lon=` for an address, `?q=` to search a place. Backs the map |
| `GET` | `/cases` | List all cases, newest first |
| `GET` | `/cases/{id}` | One case, with every intermediate result, its `stage`, and its history |
| `GET` | `/cases/{id}/photo` | The submitted photograph |
| `GET` | `/cases/{id}/envelope` | The filed envelope as written to the sandbox outbox |
| `GET` | `/cases/{id}/photo/{n}` | One of several photographs on the same report |
| `GET` | `/cases/{id}/cluster` | The pattern this case belongs to, or `null` |
| `GET` | `/cases/{id}/pack` | The evidence pack: one self-contained HTML file |
| `GET` | `/clusters` | Every repeat-report pattern found, strongest first |
| `POST` | `/cases/{id}/confirm` | The human gate; files the complaint |
| `POST` | `/cases/{id}/escalate` | Escalate once the statutory window has lapsed |
| `POST` | `/cases/{id}/acknowledge` | Record that the authority replied. Restarts the escalation clock |
| `POST` | `/cases/{id}/resolve` | The problem itself was dealt with |
| `POST` | `/cases/{id}/withdraw` | The citizen takes the complaint back. Terminal |
| `POST` | `/cases/{id}/rti` | Draft a Right to Information application, once the window has lapsed |
| `GET` | `/cases/{id}/rti` | That application as filing-ready text |
| `GET` | `/register` | The public register: filed cases only, with the reporter's contact stripped |
| `GET` | `/register/{id}` | One public case |

`POST /reports` also answers `413` if the upload is larger than the instance
accepts and `429` if the rate limit is reached — a report costs about ten model
calls against a metered free tier, so an open endpoint on a public URL is one
crawler away from an empty budget.

A case carries two separate fields. `status` is its legal lifecycle — `draft`,
`awaiting_confirmation`, `filed`, `acknowledged`, `escalated`, `resolved`,
`withdrawn`, `rejected`, `failed`. `stage` is
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

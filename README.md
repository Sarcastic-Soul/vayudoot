# Vayudoot

**A hyper-local pollution detection network in which citizen reports are one
class of sensor.**

It joins citizen photographs to satellite thermal detections, ground-station
readings and meteorology to find pollution events that macro-level monitoring
misses, forecasts where air quality is about to degrade, and hands the
responsible authority a corroborated case it can act on — drafted, jurisdiction
resolved, and tracked if it is filed.

Built on the [Strands Agents SDK](https://strandsagents.com/), with
[Gemini](https://ai.google.dev/) doing the inference. Runs on free tiers with no
credit card.

---

## The problem

India's cities monitor air quality at city scale and miss what happens at street
scale. A reference-grade station reports a number for a district; it cannot see
the waste fire behind one building, the stack venting at night, or the field
burning forty kilometres upwind of a city that will be breathing it tomorrow.
Those hyper-local events are most of the exposure and almost none of the data.

The second problem is what happens when somebody does notice. Acting on it is
hours of unglamorous work: identify what you are looking at, show it is not a
one-off, work out which of several overlapping authorities holds jurisdiction at
that exact location, write the complaint in the register the authority expects,
cite the right statute, file it, then chase it for weeks. Almost nobody does
this. The pollution continues because the paperwork defeats people, not because
the law is missing.

## The shape of the answer

**The unit of work is a hotspot, not a complaint.**

A hotspot is a place where pollution is happening, built from every signal that
agrees: a citizen's classified photograph, a VIIRS thermal detection, a station
reading past its Indian standard. Two properties do most of the work.

**A hotspot does not need a citizen report to exist.** If only reports created
them, the map would be empty everywhere nobody had used the app — which is most
of the country, and an empty map is indistinguishable from clean air. Satellite
and station evidence raise hotspots on their own, so the map has content before
anyone has opened the page. A photograph then does what only a photograph can:
it *upgrades* a hotspot, naming what is actually burning. A satellite sees heat,
not fuel.

**Corroboration gates publication.** A hotspot resting only on public
submissions has its confidence capped, however many submissions there are —
because volume is exactly what a coordinated campaign can manufacture, and a map
that can be aimed at an address is a weapon rather than a public good.

Complaint drafting, filing and escalation are all still here, and they are still
the most India-specific thing this does. They are now one of the actions
available from a detection rather than the purpose of the system.

## What it does

Two paths meet in the same store of signals.

**Detection** runs without anybody present. `scan.py` fetches NASA FIRMS thermal
detections and OpenAQ station readings for the places this instance knows about
— the coordinates of stored cases and the waypoints of the economic corridors in
[`corridors.json`](src/vayudoot/data/corridors.json) — and anything past its
Indian standard becomes a signal. Signals within two kilometres and a fortnight
of each other become a hotspot, ranked by confidence at
[`GET /hotspots`](src/vayudoot/hotspots.py).

**Reporting** is what a person does when they are standing in front of the
problem, and it runs the case end to end.

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

7. **Forecasting.** Where air quality is about to degrade, and why. Gemini reads
   an Open-Meteo pollutant forecast, an Open-Meteo wind forecast and the hotspots
   currently within reach upwind, and produces a risk window with the conditions
   driving it and the inputs it read. Reported per location and per **economic
   corridor** — the NCR, the Delhi–Mumbai corridor, the Punjab–Haryana stubble
   belt and three more, each a line of sampling points across several states.

   This is a model reasoning over public data, not a trained predictor, and it
   says so on every object it produces. Vertex AI would be the obvious tool and
   needs a billing account; there is no card. See
   [`agents/forecast.py`](src/vayudoot/agents/forecast.py).

8. **Federation.** Each deployment is a node with a region. It publishes the
   hotspots it detected on a versioned open feed and can read its neighbours',
   which is how Punjab's burning reaches a Delhi forecast a day before the smoke
   does. What is shared is a **detection layer, not trained weights** — that is
   the honest reading of "share predictive models", and the dishonest one was
   available. A neighbour's hotspots are forecasting context and are never
   republished as ours: a node that laundered a neighbour's detection would let
   one bad instance contaminate the network. See
   [`docs/federation.md`](docs/federation.md), and
   `python scripts/federation_demo.py` to watch two real nodes do it.

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
| [`docs/SCOPE.md`](docs/SCOPE.md) | What each version is, and what it deliberately is not |
| [`docs/federation.md`](docs/federation.md) | The feed contract, and how a second state stands up a node |
| [`docs/pitch/`](docs/pitch/) | Submission package: deck, video script, description |
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

Live at <https://vayudoot.onrender.com> (Render's free instance sleeps after 15
minutes idle; the first request after that takes 30-60 seconds to wake it).

```bash
docker build -t vayudoot .
docker run -p 7860:7860 --env-file .env vayudoot
```

The container binds to `$PORT` when it's set (Render assigns one at runtime)
and falls back to 7860 for a local run like the one above. The uid-1000 user is
for compatibility with hosts that require a non-root user. See
[`docs/deployment.md`](docs/deployment.md) for the free-tier reasoning and the
pre-demo checklist. Confirm `GET /health` reports `live_filing: false` on any
deployment.

## Licence

MIT. See [`LICENSE`](LICENSE).

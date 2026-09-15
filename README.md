# Vayudoot

**A hyper-local pollution detection network in which citizen reports are one
class of sensor.**

It watches for pollution events that city-scale monitoring misses — joining
satellite thermal detections, ground-station readings, meteorology and citizen
photographs into a live map of where pollution is happening — forecasts where
air quality is about to degrade, and hands the responsible authority a
corroborated case when somebody wants to act on one.

Built on the [Strands Agents SDK](https://strandsagents.com/), with
[Gemini](https://ai.google.dev/) doing the inference. Runs on free tiers with no
credit card.

Live at <https://vayudoot.onrender.com>.

---

## The problem

India monitors air quality at city scale and misses what happens at street
scale. A reference-grade station reports one number for a whole district; it
cannot see the waste fire behind one building, the stack venting at two in the
morning, or the field burning forty kilometres upwind of a city that will be
breathing it tomorrow. Those hyper-local events are most of what people actually
breathe and almost none of the data.

The second problem arrives once somebody notices one. Acting on it is hours of
unglamorous work: identify what you are looking at, show it is not a one-off,
work out which of several overlapping authorities holds jurisdiction at that
exact location, write the complaint in the register the authority expects, cite
the right statute, file it, then chase it for weeks. Almost nobody does this.
The pollution continues because the paperwork defeats people, not because the
law is missing.

## The shape of the answer

**The unit of work is a hotspot, not a complaint.**

A hotspot is a place where pollution is happening, built from every signal that
agrees: a VIIRS thermal detection, a station reading past its Indian standard, a
citizen's classified photograph. Two properties do most of the work.

**A hotspot does not need a citizen report to exist.** If only reports created
them, the map would be empty everywhere nobody had used the app — which is most
of the country, and an empty map is indistinguishable from clean air. Satellite
and station evidence raise hotspots on their own, so the map has content before
anyone has opened the page. A photograph then does what only a photograph can:
it *upgrades* a hotspot by naming what is actually burning. A satellite sees
heat, not fuel.

**Corroboration gates publication.** A hotspot resting only on public
submissions has its confidence capped, however many submissions there are —
because volume is exactly what a coordinated campaign can manufacture, and a map
that can be aimed at an address is a weapon rather than a public good.

Complaint drafting, filing and escalation are all still here, and they are still
the most India-specific thing this does. They are now one of the actions
available from a detection rather than the purpose of the system.

---

## What it does

### Detection — the map exists without anybody present

[`scan.py`](src/vayudoot/scan.py) fetches NASA FIRMS thermal detections and
OpenAQ station readings for the places this instance has reason to watch: the
coordinates of every stored case, and the waypoints of the economic corridors in
[`corridors.json`](src/vayudoot/data/corridors.json). Corridors are what give
the scan reach beyond where citizens have reported, which is most of India — a
fresh instance with no cases at all still has thirty scan points across six
corridors.

Anything past its Indian standard becomes a **signal**. Signals within two
kilometres and a fortnight of each other become a hotspot, ranked by confidence
at [`GET /hotspots`](src/vayudoot/hotspots.py). Severity comes from the observed
magnitude, never from how sure the classifier was — those are separate numbers
on a signal, and conflating them once made a single confident photograph of a
small fire read as `severe`.

The scan is **off by default**. An unattended loop calling two external APIs
should start because somebody watching the quota decided so, not because a
module was imported. `VAYUDOOT_SCAN_ENABLED=true` turns it on.

### Hotspots — a public claim about a place

A hotspot renders as an **area, never a pin**, with a one-kilometre minimum
radius. A detection drawn tightly around one building is a public accusation
against whoever occupies it whether or not a name appears, so the granularity is
a deliberate limit rather than a rendering choice. No responsible party is ever
named, anywhere.

Confidence is capped at 0.6 while the only evidence is citizen reports. It rises
when something independent — satellite or ground station — agrees. Every hotspot
displays its confidence and its corroboration state, and carries the signals
underneath it so the assertion can be taken apart.

A hotspot raised by instruments alone is `pollution_type: unclear` and the
interface calls it an **unidentified source**, with a line saying a photograph
would classify it. That is not a gap in the data; it is what a satellite can and
cannot know, stated plainly.

### Reporting — what a person does standing in front of the problem

A photograph runs the full case pipeline and, at the end, becomes a signal like
any other. See [the pipeline](#the-reporting-pipeline) below.

### Forecasting — where it is about to be bad

Gemini reads an Open-Meteo pollutant forecast, an Open-Meteo wind forecast and
every hotspot currently within 400 km upwind, and produces a risk window with
the conditions driving it and the inputs it read. Reported per location and per
**economic corridor**: the NCR, the Delhi–Mumbai Industrial Corridor, the
Punjab–Haryana stubble belt, Mumbai–Pune, Chennai–Bengaluru and
Kolkata–Durgapur, each a line of sampling points across several states.

This is a model reasoning over public data, not a trained predictor, and it says
so on every object it produces. It states conditions rather than instructions
and must never be confusable with a CPCB or IMD advisory — people act on air
quality predictions, which is the point of making them, so an unlabelled wrong
one does real harm to real lungs. Vertex AI would be the obvious tool and needs
a billing account; there is no card. See
[`agents/forecast.py`](src/vayudoot/agents/forecast.py).

When a tool fails, the forecast says so rather than guessing. A live run whose
wind lookup returned `429` reported the rate limit in its own `basis`, dropped
its confidence, and explicitly declined to claim the upwind hotspots were
contributing without wind data to check them against.

### Federation — because smoke does not stop at a state line

Each deployment is a node with a region. It publishes the hotspots it detected
on a versioned open feed and can read its neighbours', which is how Punjab's
burning reaches a Delhi forecast a day before the smoke does.

What is shared is a **detection layer, not trained weights**. That is the honest
reading of "share predictive models", and the dishonest one was available.
Federated training across state instances is a real idea, it is not what this
does, and claiming it would cost more than it earns.

A neighbour's hotspots are forecasting context and are never republished as
ours: a node that laundered a neighbour's detection would let one bad instance
contaminate the network, and nobody downstream could tell whose evidence a
hotspot rested on. A feed reporting our own node id is refused outright.

See [`docs/federation.md`](docs/federation.md) for the contract, and
`python scripts/federation_demo.py` to watch two real nodes do it on one
machine — no mocking, the real HTTP path.

### Citizen sensors

`POST /sensors/readings` accepts a low-cost sensor reading as a signal. It is
believed less than a reference-grade station and deliberately sits outside the
set of sources that count as independent corroboration: a station is operated by
somebody accountable and sited to a standard, while a low-cost sensor may be
indoors, beside a kitchen, or reporting whatever its owner wants it to. Genuine
evidence, weaker evidence.

---

## The reporting pipeline

One of the actions available from a detection, and the most India-specific thing
here. It runs end to end on one photograph.

0. **Intake.** The photograph is decoded rather than taken at its word. Anything
   Pillow can read is accepted — around seventy formats, including HEIC from an
   iPhone, AVIF, TIFF, BMP and JPEG 2000 — converted into one a model accepts,
   turned upright if it carries an EXIF rotation, and capped at 1568 pixels on
   the longest edge. See [`images.py`](src/vayudoot/images.py).
1. **Evidence.** Multimodal classification into a pollution category, with a
   severity estimate, the visible indicators that drove it, and a calibrated
   confidence. Up to four photographs are read together as one event. A report
   with no photograph at all is still classifiable from a written account that
   names observable things, at a confidence that says it was testimony rather
   than a picture. Below a floor of 0.55 the case halts for human review rather
   than proceeding.
2. **Corroboration.** Three independent sources are queried in parallel by a
   Strands agent graph — NASA FIRMS, OpenAQ and Open-Meteo wind — and a
   synthesis node joins them. The plume is back-traced upwind to a plausible
   source. The result is an evidence packet, not one photograph.
3. **Jurisdiction.** The coordinates are reverse geocoded and matched against a
   data-driven authority table to find who is responsible, under which statute,
   with what statutory response window, and who it escalates to. This is the
   step citizens most often get wrong.
4. **Drafting.** A formal complaint in the register the authority expects,
   citing only the statute supplied, in English and in the region's main
   language. If the report joins a **cluster** of earlier reports of the same
   problem at the same place, the complaint says so — a pattern is the argument
   a regulator acts on, and fifteen reports over a month is a categorically
   different case from one.
5. **Filing and tracking.** A human confirms, the complaint is filed, and the
   case is tracked through its whole life: escalated when the statutory window
   lapses, **acknowledged** when the authority replies, **resolved** when the
   problem stops, **withdrawn** if the citizen takes it back. An acknowledgement
   restarts the escalation clock rather than stopping it — it is a receipt, not
   a remedy, and one automated "your complaint has been received" should not
   silence the tracker forever.
6. **Pressing further.** When the window lapses, the real lever is not a second
   email but a **Right to Information application** to the authority's Public
   Information Officer, which carries a statutory thirty-day duty to reply that
   the complaint never had. The agent drafts one, with every field a human must
   supply marked in the document.

---

## The interface

One page of Preact components running as native ES modules — **no bundler, no
build step, no Node** — served by the same FastAPI process that runs the agents,
because this is used on a phone while standing in front of the problem. Preact
and htm are vendored into [`web/vendor/`](src/vayudoot/web/vendor/) rather than
fetched from a CDN: a third party in the request path of a page a citizen uses
to report pollution was avoidable. Leaflet, for the maps, is the one exception.

**The operations view is the landing surface.** The empty hash routes to `ops`,
not to the report form — what a state air quality cell opens in the morning is a
map of what is happening, not a blank submission page. It carries the hotspot
map and the ranked list; each card shows severity, confidence, corroboration
state and how many of the signals underneath it came from which source. Opening
one shows its extent on the map and every signal it rests on, with each signal's
time, strength and magnitude.

Navigation is **Live**, **Report**, **Cases** and **Coverage**. The shell is one
grid, and the only thing that changes with width is where the navigation sits: a
bar under the thumb on a phone, an icon rail on a tablet, a labelled sidebar on
a desktop, which collapses back to a rail on request. Wide screens get two
columns rather than a wider column, since a complaint is easier to read at 70
characters than at 130. Either map expands to fill the screen — 300px is enough
to confirm a pin and not enough to find one.

Themes are three-state — light, dark, or follow the system — and the choice is
remembered. There is a skip link, the sections are addressable (`#cases`,
`#coverage`, `#VDH-XXXXXXXX`) so the back button works, the case status is a
live region so a stage change is announced while the page polls, and
`prefers-reduced-motion` and `prefers-contrast` are both honoured.

- Take the photograph, then place the pin. The map is the location input: it is
  there from the moment the page loads, the browser's location moves it if you
  allow that, searching a place name moves it, and dragging or tapping always
  works. What you read back is the address, not a coordinate — nobody knows
  their own latitude.
- A **Coverage** tab lists every authority this instance can resolve to, and
  says plainly that all the addresses are `.invalid` placeholders. When a case
  falls back to a broader authority than the statute names, or to the generic
  placeholder, the case says so instead of presenting it as a match.
- A run is minutes of model calls, so the submission returns immediately with a
  case id and the page polls it. Every stage's output appears as it lands.
- The complaint is shown in English and in the region's language, with a single
  **Confirm and file** button. Nothing moves until that is pressed.
- The filed envelope is shown exactly as it was written to the sandbox outbox.

## Who can see what

There is no login, by design — an anonymous submission and a contact string is
the whole model. That makes the privacy boundary a matter of what each surface
publishes, so it is drawn explicitly rather than left to convention.

The citizen's contact is needed inside the process: an RTI application names an
applicant, and clustering counts distinct reporters. It never leaves it. Every
route that returns a `Case` excludes it, and a test fails when a new one
forgets.

The **public register** goes further and is an allowlist, not a denylist, so a
field added to `Case` later is private by default. It carries only filed,
acknowledged, escalated and resolved cases: a case that halted below the
confidence floor is not something to publish about a place, and a withdrawn case
leaves the register entirely, because withdrawal revokes exactly the consent it
runs on. A case that is not public answers `404` rather than `403`, so the
register cannot be used to confirm that a withdrawn complaint was ever made.

The **federation feed** is an allowlist for the same reason. It carries a
hotspot's location, extent, confidence, severity and corroboration state — and
no signals and no case ids. A neighbour needs to know that something is burning
and how sure we are; it has no business knowing which of our citizens reported
it.

The **evidence pack** omits the contact too, and says so in the document — its
whole purpose is to be handed to somebody else.

## Safety

Three decisions are load-bearing and are enforced by tests.

**Live filing is off.** Every run writes to a local sandbox outbox. Setting
`VAYUDOOT_LIVE_FILING=true` raises rather than sends, because no delivery
transport is wired in on purpose. An unattended prototype must not be able to
email a real pollution control board.

**Every committed authority email is non-routable**, on the reserved `.invalid`
TLD. Authority names are real and public; the addresses are not. Real contact
details belong in an uncommitted `authorities.json`.

**Nothing predictive presents itself as official.** Every forecast carries its
disclaimer, its inputs and its confidence on the object itself, not only in the
interface that happens to render it.

Alongside those, classification confidence is surfaced to the user, a human
confirms before anything is filed, and the drafting prompt forbids naming an
accused party or claiming certainty the evidence does not support.

## Documentation

| | |
| --- | --- |
| [`docs/architecture.md`](docs/architecture.md) | How the pieces fit together and why |
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
  DETECTION — nobody present              REPORTING — a person is there
  ───────────────────────────             ─────────────────────────────

  NASA FIRMS       OpenAQ                  up to 4 photos, or a note
  thermal          stations                          │
      │               │                              ▼
      └───────┬───────┘                     ┌──────────────────┐
              ▼                             │    1 Evidence    │
      ┌───────────────┐                     │  classification  │
      │    scan.py    │                     │  below 0.55 →    │
      │  hourly, off  │                     │  halt for human  │
      │  by default   │                     └─────────┬────────┘
      └───────┬───────┘                               ▼
              │                             ┌──────────────────┐
              │    citizen sensor           │ 2 Corroboration  │
              │    POST /sensors/readings   │  FIRMS · OpenAQ  │
              │         │                   │  wind, parallel  │
              ▼         ▼                   └─────────┬────────┘
        ┌───────────────────┐                         │
        │      signals      │◀────────────────────────┤
        └─────────┬─────────┘   a classified case     │
                  ▼             is a signal too       ▼
      ┌───────────────────────┐              ┌─────────────────┐
      │      hotspots.py      │              │  3 Jurisdiction │
      │  2 km · 14 d linkage  │              └────────┬────────┘
      │  minimum radius 1 km  │                       ▼
      │  uncorroborated ≤ 0.6 │              ┌─────────────────┐
      └───────────┬───────────┘              │   4 Drafting    │
                  │                          └────────┬────────┘
       ┌──────────┼──────────┐                        ▼
       ▼          ▼          ▼               ┌─────────────────┐
  GET /hotspots  forecast  GET /feed         │   human gate    │
    the map      + corridor  federation      │ nothing files   │
                  outlook    ▲               │ itself          │
                             │               └────────┬────────┘
                    GET /neighbours                   ▼
                    a neighbour's detections  ┌─────────────────┐
                    are forecasting context,  │  5 File & track │
                    never republished as ours │  escalate · ack │
                                              └────────┬────────┘
                                                       ▼
                                                6 RTI, once the
                                                window has lapsed
```

</details>

## Model providers

No module constructs a provider directly. `vayudoot.models.build_model()` reads
the configured provider at runtime, so the same agent code runs on Google Gemini
or on Ollama with one environment variable changed.

Models come in two tiers. `primary` is judgement — reading a photograph, drafting
a legal complaint. `fast` is mechanical — call one tool, summarise the output.
The shipped configuration puts **both on Gemini**: primary on Flash, fast on
Flash-Lite. The tier split survives as a cost control inside one provider, since
only two of the ten model calls a report makes need judgement.

Ollama remains supported for local development and the offline test suite. A
system a state could run on its own hardware is part of the deployability
argument, so the abstraction earns its keep.

```bash
VAYUDOOT_MODEL_PROVIDER=gemini   # or ollama
```

## Data sources

| Source | Used for | Key |
| --- | --- | --- |
| NASA FIRMS | satellite thermal anomalies | free |
| OpenAQ v3 | ground station pollutant readings | free |
| Open-Meteo | wind speed and direction, plume back-trace | none |
| Open-Meteo Air Quality | pollutant forecast for the outlook | none |
| OpenStreetMap Nominatim | reverse geocoding | none |

Exceedance is measured against the **NAAQS** thresholds in the Indian standard
(CPCB notification S.O. 384(E), 2009), held in configuration in µg/m³ with unit
conversion at the boundary. An unrecognised unit is refused rather than assumed
— a real CO reading of 1680 µg/m³, which is below the standard, once scored
maximum severity because the table held the standard in mg/m³.

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
`uv run python scripts/federation_demo.py` starts two real nodes and shows
Punjab detecting while Delhi forecasts.

### Endpoints

**Detection and the map**

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/hotspots` | Every active hotspot, most confident first |
| `GET` | `/hotspots/{id}` | One hotspot with the signals underneath it |
| `POST` | `/sensors/readings` | Submit a low-cost sensor reading as a signal |

**Forecasting**

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/forecast` | `?lat=&lon=&place=` — outlook for one location |
| `GET` | `/corridors` | The economic corridors this instance forecasts along |
| `GET` | `/corridors/{id}/forecast` | One corridor's outlook, worst waypoint first |

**Federation**

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/node` | Who this instance is |
| `GET` | `/feed` | This node's hotspots, as a versioned document |
| `GET` | `/neighbours` | What each configured peer is reporting, and which failed |

**Reporting**

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/reports` | Submit a photo and coordinates. Returns `202` with a case id and runs the pipeline in the background, or `415` if the file is not a readable image |
| `GET` | `/cases` | List all cases, newest first |
| `GET` | `/cases/{id}` | One case, with every intermediate result, its `stage`, and its history |
| `GET` | `/cases/{id}/photo` | The submitted photograph |
| `GET` | `/cases/{id}/photo/{n}` | One of several photographs on the same report |
| `GET` | `/cases/{id}/envelope` | The filed envelope as written to the sandbox outbox |
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

**Public and supporting**

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/register` | The public register: filed cases only, with the reporter's contact stripped |
| `GET` | `/register/{id}` | One public case |
| `GET` | `/authorities` | The jurisdiction table this instance runs on, and its coverage counts |
| `GET` | `/geocode` | `?lat=&lon=` for an address, `?q=` to search a place. Backs the map |
| `GET` | `/health` | Active provider, and confirmation that live filing is off |

`POST /reports` also answers `413` if the upload is larger than the instance
accepts and `429` if the rate limit is reached — a report costs about ten model
calls against a metered free tier, so an open endpoint on a public URL is one
crawler away from an empty budget.

A case carries two separate fields. `status` is its legal lifecycle — `draft`,
`awaiting_confirmation`, `filed`, `acknowledged`, `escalated`, `resolved`,
`withdrawn`, `rejected`, `failed`. `stage` is how far the machinery has got —
`received`, `evidence`, `corroboration`, `jurisdiction`, `drafting`, `complete`,
`halted`. That split is what lets the interface show progress during the minutes
a case spends in `draft`. A run that fails leaves `stage` parked on whatever was
running when it died.

## Coverage

Everything region-specific is data, not code, which is what decides whether this
becomes a national system or stays a Delhi demo.

- **Authorities** — all 28 states and 8 union territories at state tier, in
  [`authorities.example.json`](src/vayudoot/data/authorities.example.json).
  Adding a municipal body is a JSON edit.
- **Corridors** — six, in [`corridors.json`](src/vayudoot/data/corridors.json),
  spanning eleven states and union territories. Waypoints are sampling points,
  not a route.

## Deploying

Live at <https://vayudoot.onrender.com> (Render's free instance sleeps after 15
minutes idle; the first request after that takes 30-60 seconds to wake it).

```bash
docker build -t vayudoot .
docker run -p 7860:7860 --env-file .env vayudoot
```

The container binds to `$PORT` when it's set (Render assigns one at runtime) and
falls back to 7860 for a local run like the one above. The uid-1000 user is for
compatibility with hosts that require a non-root user. See
[`docs/deployment.md`](docs/deployment.md) for the free-tier reasoning and the
pre-demo checklist. Confirm `GET /health` reports `live_filing: false` on any
deployment.

## Licence

MIT. See [`LICENSE`](LICENSE).

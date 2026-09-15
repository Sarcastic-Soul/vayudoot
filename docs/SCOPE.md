# Scope — v0.1

The point of this file is the non-goals. The build window is short, and the
failure mode for a project like this is a broad demo where nothing works end to
end. A narrow system that genuinely runs beats a wide one that only renders.

**v0.1 is done when** a person can submit a photograph and coordinates from a
phone browser, watch the case move through every stage, read the drafted
complaint, confirm it, and see it land in the outbox — running on a public URL,
not on localhost.

That sentence is the whole target. Anything that does not serve it is out.

---

## In scope

### Pipeline
- [x] Evidence classification from a photograph, with a confidence floor that
      halts the case for human review
- [x] Corroboration graph: satellite, ground station, meteorology in parallel
- [x] Plume back-trace to a candidate upwind source
- [x] Jurisdiction resolution against a data-driven authority table
- [x] Complaint drafting in English plus the region's main language
- [x] Sandboxed filing with a statutory-window escalation timer
- [x] One real end-to-end run against a real photograph, start to finish —
      needs credentials; every stage is exercised offline by the test suite

### Interface
- [x] A single-page web interface: submit a report, see the case, confirm filing
- [x] Mobile browser first — this is used standing in front of the problem
- [x] Case timeline showing every stage's output, not just the final complaint
- [x] A map of submitted cases
- [x] Location is chosen on a map, by search or by pin, never by typing
      coordinates
- [x] A coverage view listing every authority the instance can resolve to, and
      an in-case warning when a match was a fallback or a placeholder

### Delivery
- [x] Deployed on a public URL, free tier, no credit card — live at
      https://vayudoot.onrender.com
- [x] Frontend served by the same FastAPI process, so there is one deployment
- [x] `README.md` and `docs/architecture.md` accurate to what actually ships
- [x] Architecture diagram as an image, not only the ASCII sketch

### Data
- [x] Authority table covering enough regions for the demo location to resolve
      to a specific authority rather than the generic fallback
- [x] The table's coverage is published and every fallback is reported on the
      case that used it

---

## Out of scope for v0.1

Each of these is a reasonable idea. None is being built now.

**Accounts and authentication.** No login, no user accounts, no roles. The demo
works with an anonymous submission and a contact string. Adding auth costs a day
and improves nothing a viewer can see.

**A real delivery transport.** Not a missing feature — a safety property. See
`CLAUDE.md`.

**A database.** Cases are JSON files. Postgres is a `store.py` rewrite whenever it
is actually needed; it is not needed to demonstrate the system.

**Voice intake and multilingual input.** The complaint is *drafted* in the local
language, which is the part that matters for filing. Accepting voice notes in a
local language is a different problem and a different set of API costs.

**A messaging-app front end.** WhatsApp and Telegram intake would be the right
real-world channel and is the obvious next step. It needs business verification
or a bot deployment, and neither earns its cost inside this window.

**Automatic escalation on a timer.** The escalation logic and the statutory
deadline are implemented and reachable through the API. Running it unattended on
a scheduler means an unsupervised process acting on a legal deadline. It stays
manual.

**Federated or cross-region model sharing.** Interesting architecture, invisible
in a demo.

**Live satellite imagery tiles.** FIRMS detections already provide the satellite
evidence. Earth Engine or Sentinel Hub tiles are a rabbit hole.

**Identifying the responsible party.** The system deliberately does not name an
accused party. It reports an observation to an authority. Naming a person or a
business from a photograph is both technically unreliable and a serious harm if
wrong.

---

# Scope — v0.2

v0.1 froze scope hard because the build window was short. That window is no
longer the binding constraint, so the following moved from "reasonable idea" to
"being built". Each entry says what it is and why it earns its place; the
non-goals above that are not repeated here stay non-goals.

## Finishing what v0.1 claimed

- [x] **Case lifecycle.** `ACKNOWLEDGED` and `RESOLVED` existed in the status
      enum with nothing able to set them, so "track and escalate" was half true:
      a case could be filed and escalated but never recorded as answered or
      settled, and `escalation_due()` kept reporting an answered case as overdue.
      Adds acknowledge, resolve and withdraw, and makes the escalation clock
      respect them. This is not a new feature; it is an unfinished one.

- [x] **Rate limiting and upload caps.** `POST /reports` is open and each report
      spends roughly ten metered model calls from a free tier. On a public URL
      one crawler empties the day's budget. The upload path also reads an
      unbounded body into memory before decoding it. Both are prerequisites for
      the public deployment that was already in scope.

## New capability

- [x] **Prompt evaluation harness.** The corroboration stage has been wrong twice
      — once discarding its own structured output, once inventing corroboration
      from a wind bearing — and both times only a live run caught it. Prompts are
      now being edited regularly with no way to tell whether a change helped.
      A fixture set with expected classifications, scored for accuracy and
      confidence calibration, is what makes every other change safe.

- [x] **Clustering repeat reports.** Fifteen reports at one location over a month
      is a categorically stronger complaint than one, and a pattern is the
      argument a regulator actually acts on. Uses only data already stored and
      needs no new external API.

- [x] **RTI follow-up drafting.** When the statutory window lapses, an Indian
      citizen's real lever is not a second email — it is a Right to Information
      application asking what action was taken. This is the most India-specific
      thing the project can do, and it turns escalation from repetition into
      something with legal weight.

- [x] **Evidence pack.** One document carrying the photograph, the corroboration
      data, the map, the complaint and the timeline — something that can be
      attached, printed, or handed to a journalist or an NGO. Served at
      `GET /cases/{id}/pack` as one self-contained HTML file: the complaint is
      drafted in the region's language as well as English, and a browser already
      shapes Devanagari, Kannada and Tamil correctly where most pure-Python PDF
      writers silently drop the glyphs. It prints to PDF from anywhere, needs no
      new dependency, and opens offline — photographs are embedded as data URIs
      and the map is an SVG drawn from the case's own coordinates rather than a
      tile fetched from a service. See `pack.py`.

- [x] **Public case register.** Cases are already deep-linkable; making one
      shareable read-only turns individual complaints into a visible record,
      which is where most of the accountability value lives. `GET /register`
      publishes only cases a human confirmed and filed — a withdrawn case leaves
      it, and a rejected, failed or unconfirmed one never enters. The projection
      is an explicit allowlist in `register.py`, so a field added to `Case` later
      is private until somebody publishes it deliberately. The reporter's
      contact and their free-text note are never in it.

- [x] **Multiple photographs per report.** One angle is often not enough to
      classify confidently, and the confidence floor then halts a real event.
      `Report.image_paths` is a list, capped at four because every photograph is
      an image block in the same evidence call and therefore quota. Cases stored
      under the old single `image_path` key still load, and `/cases/{id}/photo`
      still means the first photograph.

## Still out of scope, and why

The non-goals above stand, and three of them are worth restating because they
are the ones most likely to be argued for now that the schedule has loosened.

**A real delivery transport** and **automatic escalation on a timer** are safety
properties rather than missing features. An unsupervised process acting on a
legal deadline, or a misconfigured run reaching an actual regulator, is a
different class of risk from a bug.

**Identifying the responsible party** stays out permanently. It is unreliable
from a photograph and seriously harmful when wrong.

---

## Rules for changing this file

Moving something from out-of-scope to in-scope is a decision, not a drive-by
edit. Write the reason next to the entry when you move it, in the entry itself —
an item with no stated reason is an item nobody can argue with later.

Adding something that appears on neither list means it was never considered.
Consider it first.

---

# Scope — v0.3: the Code for Communities pivot

## What changed and why this section is long

The AWS hackathon is dropped. The new target is **Build with AI: Code for
Communities — Second Edition**, a Google Cloud / Hack2skill / GDG India event,
**problem statement 02, Clean Air & Climate Resilience**. The brief, the rules
and the evaluation weights are in `PROBLEM-STATEMENTS.md`; read that before
arguing with anything here.

**Hard deadline: 30 September 2026.** At the time of writing, sixteen days.

The first pass at this section assumed the pivot was a matter of adding two
missing features. That was wrong, and it is worth saying so rather than quietly
rewriting: the point of view is wrong, not the feature list.

## The diagnosis

**Vayudoot's protagonist is a citizen with a grievance.** The unit of work is a
*case*: one report becomes one complaint to one authority, tracked to
resolution. The API says so plainly — twenty-three routes, seventeen of them
under `/cases/{id}`. The verbs are classify, corroborate, draft, file, escalate.

**The brief's protagonist is a city or state air quality cell.** The unit of work
is a *hotspot*: a place where pollution is happening that macro-level monitoring
missed, carrying a severity, a trend and a forecast. The verbs are detect,
forecast, alert, coordinate, share.

These are not the same product. A complaint desk that happens to collect data is
not a climate action platform, however good the complaints are.

**But the bridge is already built, and it is the best part of the system.** A
citizen photograph on its own is an anecdote. Joined to FIRMS thermal
detections, OpenAQ station readings and wind data by the corroboration graph, it
becomes a *measurement* — which is exactly what the brief means by combining
citizen-sourced data with satellite imagery and meteorological data. That
machinery is already written, already tested, and already better than the brief
asks for. The error was pointing its output at a complaint letter instead of at
a map.

## The reframe

Vayudoot stops being a complaint desk that gathers data along the way, and
becomes **a hyper-local pollution detection network in which citizen reports are
one class of sensor**. Complaint drafting, filing and RTI survive — demoted from
the product's purpose to one of the actions available from a detection, which is
what "alert relevant authorities for rapid intervention" actually describes.

Nothing already built is thrown away. `images.py`, the evidence agent, the
corroboration graph, every tool, jurisdiction, drafting, the evidence pack, the
public register, storage, rate limiting and the model layer all carry over
unchanged. What changes is what sits on top of them and what the front door
shows.

### The new spine: `Hotspot`

A hotspot is a place and a pollution type, carrying a confidence, a severity
trend over time, the signals supporting it, a forecast, and the jurisdiction
that owns it.

`Cluster` in `schemas.py` is already most of this object — it has an id, a
pollution type, a centroid, members and a time window, and `clustering.py`
already contains the three hard judgements about what makes two observations
*the same problem*. The work is promotion, not invention: widen its inputs,
give it a forecast and a severity score, and make it a first-class stored object
rather than a view computed over cases.

### The one decision that changes the whole build

**A hotspot must not require a citizen report to exist.**

Today, clustering runs over cases, so a hotspot can only exist where somebody
photographed something. That is the failure mode of every crowdsourced platform:
the map is empty in every district where nobody has reported yet, which is most
of India, and an empty map is indistinguishable from clean air.

So satellite detections and station anomalies must **also** seed hotspots. FIRMS
covers the whole country and publishes continuously, which means the map has
content nationally from the first minute, before a single citizen has used the
app. A citizen photograph then does the thing it is uniquely good at: it
*upgrades* a hotspot — raising its confidence, naming what is actually burning,
and turning a thermal anomaly into a classified, describable event that a
complaint can be written about.

This also settles a problem the citizen-only design had no answer for. Fifteen
coordinated fake reports would have manufactured a hotspot. Under the new rule a
hotspot's confidence is capped unless independent evidence agrees, and the
corroboration graph that produces that agreement is already written.

### Two faces, one system

- `/` — **the operations view.** Map first: live hotspots ranked by severity,
  corridor forecasts, the evidence behind each, and the alert an authority can
  raise from one. This becomes the landing surface.
- `/report` — **citizen intake**, the existing form and pipeline, unchanged.
- `/register` — **the public record**, the existing register, unchanged.

No login. A real operations console would have roles, and roles cost a day and
show nothing — but more than that, a *public* dashboard is the stronger position
for something claiming to be a digital public good: everyone sees the same air
data, which is the whole argument. "Authority view" is a view, not an account.

## In scope for v0.3

Ordered by marks per day, which is the only sensible order with sixteen days
left. Rubric weights are in `PROBLEM-STATEMENTS.md`.

- [x] **Both tiers on Gemini.** Rule 1: no Google AI, no consideration. Done.

- [x] **`Hotspot` as a first-class object, seeded from satellite and station
      data as well as citizen cases.** This is the pivot; everything below
      depends on it existing.

      Landed: `Signal` and `Hotspot` in `schemas.py`, detection in
      `hotspots.py`, the shared centroid-linkage rule extracted to
      `grouping.py` so clustering and detection cannot drift apart, and
      `GET /hotspots`. Signal builders exist for all three sources, so a
      satellite detection or a station exceedance raises a hotspot on its own
      and a citizen photograph upgrades one — proven by test, not asserted.

      Two corrections worth recording. The object is **derived, not stored**:
      what needs storing is the *signals*, since a satellite scan cannot be
      recomputed after the fact the way a case can be re-read, while membership
      changes whenever a signal arrives. And `Signal` carries **both** a
      `strength` and a `magnitude`, because the first version conflated them and
      reported one confident photograph of a small fire as `severe` — a model
      being sure of what it saw is not the same as what it saw being serious.

      The scan landed with it: `scan.py` fetches FIRMS and OpenAQ into the
      signal store for the coordinates of stored cases and the waypoints of
      configured corridors, and `hotspots.current()` reads both halves. It runs
      on a timer through the app lifespan, gated off by default.

- [x] **The operations view as the landing surface.** Map, ranked hotspot list,
      drill-down to every signal a hotspot rests on. Reuses the existing shell,
      map components and theming. Hotspots render as areas at their true radius
      and confidence never appears without its corroboration state, both of
      which are constraint 7 rather than taste.

- [x] **Forecasting.** The brief names it and nothing in the system predicted.
      Vertex AI is the obvious tool and is excluded by the free-tier constraint,
      so: Open-Meteo's 72-hour forecast, recent OpenAQ history, and the hotspots
      currently active upwind, joined by a Gemini call with structured output
      into a risk window with a stated confidence and its reasoning.

      This is a model reasoning over real data, not a trained predictor, and it
      must be labelled as exactly that everywhere it appears. An overclaimed
      forecast is worse than an honest one: a judge who finds the label learns
      the project is careful, and one who finds the overclaim learns the
      opposite.

- [x] **Economic corridors as data.** The brief says "across major economic
      corridors", so they are named objects, not an abstraction: NCR, the
      Delhi–Mumbai Industrial Corridor, the Punjab–Haryana stubble belt,
      Mumbai–Pune, Chennai–Bengaluru. A JSON file beside `authorities.example.json`,
      because jurisdiction data is data. Forecasts are reported per corridor.

- [x] **Federation, demonstrated rather than asserted.** Each deployment is a
      **node** with a declared region. A node publishes its hotspots on an open,
      versioned feed and can subscribe to a neighbour's.

      The demo this exists for: a Punjab node detects stubble burning; the Delhi
      node ingests it and its forecast shows the incoming plume a day and a half
      before it arrives. That is the actual story of Indian air pollution, it is
      the clearest possible answer to "share predictive models and coordinate
      resources", and it needs no model training.

      Be precise about the claim. What is shared is a **detection layer** —
      hotspot feeds, corridor definitions, detection thresholds, the authority
      table — not trained weights. Sharing weights is not happening in sixteen
      days, and claiming it in a deck without building it costs more than it
      earns.

- [x] **Citizen sensor readings.** The brief's own sentence is "photos, local
      sensor readings", and only the first half exists. An endpoint accepting a
      reading from a low-cost PM sensor, feeding hotspot confidence the same way
      a station reading does. A schema and a route.

- [x] **Authority table to full national coverage.** All 28 states and 8 union
      territories, plus aliases for the pre-2020 names geocoders still return.
      Union territories have Pollution Control Committees rather than Boards and
      the entries reflect that. All 159 committed addresses are on `.invalid`.

- [ ] **Submission package.** Public repo (already), a 3–5 minute end-to-end
      demo video, a 10–12 slide deck, a 2–3 line description, the deployed link.
      Under these weights the deck is where Deployability and Impact are
      actually argued. It needs days, not the last evening.

## Under consideration, not committed

- **Population exposure per hotspot.** "Threatens public health" is the brief's
  own framing and Impact Potential is 15%. A coarse district population density
  table shipped as data would give every hotspot a number of people. Cheap if
  the data is clean, droppable if it is not.

- **ISRO / Bhuvan or Earth Engine imagery.** The organisers name both, and FIRMS
  detections are not imagery. Free on a noncommercial registration. Decide by
  day four or drop it; v0.1 already called tiles a rabbit hole and was right.

- **CPCB / data.gov.in station data alongside OpenAQ.** More India-specific than
  OpenAQ and named by the organisers. Cheap if the endpoint behaves.

## Still out of scope

Every non-goal from v0.1 and v0.2 stands unless listed above. Four are worth
restating because the new brief reads as an invitation to build them.

**Accounts, logins and roles.** Decided above: the operations view is public.

**Voice intake.** Cloud Speech-to-Text needs a billing account and there is no
card. Track 02 does not ask for voice; track 01 does, and we are not entering
track 01.

**Training or exchanging models between nodes.** Federation is reversed only as
far as the data contract. Actual federated learning is not happening in sixteen
days.

**A real delivery transport, automatic escalation, and naming a responsible
party.** Safety properties, and the reframe makes the third one sharper rather
than softer — see hard constraint 7 in `CLAUDE.md`. "Alert relevant authorities"
does not change any of them.

## The free-tier constraint, settled

There is no card. Google Cloud's free tier — the $300 trial and the Always Free
products alike — requires a Cloud Billing account, which requires a card on file
even though it is never charged. So Vertex AI, Cloud Run, Cloud Functions, Maps
Platform, Speech-to-Text, Text-to-Speech and Translation are all unavailable.

The Gemini API through Google AI Studio needs a Google account and nothing else,
which is why it is the one Google service this project uses — and it happens to
be the one the rules require. Hosting stays on Render; nothing in the rules asks
for Google Cloud hosting, only Google AI.

This is settled, not pending. A plan that assumes a card will appear is not a
plan, and anything that could only be built on Vertex AI is built another way or
is not built.

## Eligibility, settled

Rule 2 disqualifies pre-existing projects "unless substantially extended for
this challenge". The first commit is dated 6 September 2026 and the window
opened 11 August 2026, so the whole repository was written inside it. The work
above is a substantial extension on top of that. Nothing here depends on
arguing the point, but the point is worth not losing.

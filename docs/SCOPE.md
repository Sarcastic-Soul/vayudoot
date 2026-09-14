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

## Why this section exists

v0.1 and v0.2 were built for an AWS hackathon. That target is dropped. The new
target is **Build with AI: Code for Communities — Second Edition**, a Google
Cloud / Hack2skill / GDG India event, **problem statement 02, Clean Air &
Climate Resilience**. The brief, the rules and the evaluation weights are
recorded verbatim in `PROBLEM-STATEMENTS.md`; read that file before arguing with
anything below.

**Hard deadline: 30 September 2026.** At the time of writing that is sixteen
days.

This is a change of target, not a change of product. The pivot is cheap because
the thing already built is close to what the new brief asks for — but "close" is
not "aligned", and the gaps are where the marks are.

## Eligibility, settled

Rule 2 disqualifies pre-existing projects "unless substantially extended for
this challenge". The first commit is dated 6 September 2026 and the hackathon
window opened 11 August 2026, so the entire repository was written inside the
window. The work in this section is a substantial extension on top of that.
Nothing here depends on arguing the point, but the point is worth not losing.

## What the new brief asks for, against what exists

The challenge text: *combine citizen-sourced data (photos, local sensor
readings) with satellite imagery and meteorological data; detect hidden
pollution hotspots; forecast air quality spikes across major economic corridors;
alert relevant authorities for rapid intervention; designed for interoperability
so Indian cities and states can share predictive models and coordinate
resources.*

| Clause | Where it stands |
| --- | --- |
| Citizen photos | Built. Evidence stage, up to four photographs per report. |
| Local sensor readings | Built. OpenAQ ground stations. |
| Satellite imagery | Partial. FIRMS thermal detections, no imagery. |
| Meteorological data | Built. Open-Meteo, plus the upwind back-trace. |
| Detect hidden hotspots | Built. Clustering is exactly this, and it is the strongest existing answer to the brief. |
| **Forecast air quality spikes** | **Missing entirely.** Nothing in the system predicts. |
| Alert authorities | Built, and deliberately stops short of delivery. See below. |
| **Interoperability / sharing across states** | **Explicitly a non-goal in v0.1**, on the grounds that it is invisible in a demo. That reasoning is now wrong: it is 40% of the score. |

The evaluation weights are the real specification. Depth & Reach Across India
(20%) plus Deployability & Scalability (20%) are 40% of the total and reward the
architecture and the scale story rather than features. Problem-Solution Fit is a
further 20% and is scored against the clause list above, including the two rows
marked missing.

## Constraint changes

### New hard constraint: Google AI, and it is not optional

Rule 1 of the event: no Google AI, no consideration. This is now recorded in
`CLAUDE.md` as hard constraint 6. The shipped configuration must put **both**
tiers on Gemini.

This partly voids the two-provider split described in hard constraint 5. That
split existed to spread one report across two free tiers, with the two judgement
calls on Ollama and the eight mechanical ones on Gemini. Under the new rules
that arrangement puts the only calls a judge would call meaningful — reading the
photograph, drafting the complaint — on a non-Google model, which is the
specific thing rule 1 forbids.

What survives: the **tier split itself**, as a cost control within one provider,
primary on Gemini flash and fast on Gemini flash-lite. What changes: the shipped
`.env` flips to `VAYUDOOT_MODEL_PROVIDER=gemini` with the fast override either
unset or also `gemini`. What stays: `build_model()` as the only place a provider
is constructed, and Ollama as a working offline path for development and for the
test suite. The abstraction is not being removed — it is what makes the claim
"this runs on a state's own infrastructure" true rather than aspirational, and
that claim is worth marks under Deployability.

### Unchanged: nothing reaches a real regulator, and a human confirms

Hard constraints 1 and 2 stand exactly as written. The brief says "alert
relevant authorities for rapid intervention"; the system drafts, addresses and
raises the alert, and does not deliver it. Every committed address stays on
`.invalid`, `tests/test_filing_safety.py` stays as it is, and the pipeline
continues to halt at `AWAITING_CONFIRMATION`.

This is a deliberate position and should be presented as one in the deck rather
than hidden: a prototype that can email a real State Pollution Control Board
during a demo is a liability, and a system that files on a citizen's behalf
without their confirmation is a worse one. Say so on a slide.

### Free tier, under a new kind of pressure

Hard constraint 3 is unchanged and is now the binding constraint on which Google
services can be used, because the recommended stack is split down the middle by
it:

**Usable — genuine free tier, no card:** Gemini API via Google AI Studio;
BigQuery sandbox; Firebase Spark plan; Google Earth Engine on a noncommercial
registration.

**Not usable without a billing account and a card:** Vertex AI, Cloud Run, Cloud
Functions, Google Maps Platform, Cloud Speech-to-Text, Cloud Text-to-Speech,
Cloud Translation.

Two consequences. The deployment stays on **Render**, which already works and is
already live — nothing in the rules requires hosting on Google Cloud, only that
Google AI is integrated. And **Vertex AI is off the table**, which decides the
shape of the forecasting work below.

There is no card, and this is settled rather than pending. A service that needs
one is not a candidate, and a plan that assumes one will appear is not a plan.
Anything below that could only be built on Vertex AI is built another way or is
not built.

## In scope for v0.3

Ordered by marks per day, which is the only sensible order with sixteen days
left.

- [ ] **Both tiers on Gemini.** Flip the shipped configuration, update
      `docs/deployment.md` — which still says "AWS credits" in its cost table —
      and update the README's framing. Half a day, and rule 1 makes it the one
      item that is not optional.

- [ ] **Authority table to full national coverage.** 24 states are present; 28
      states and 8 union territories exist. The missing entries are the
      north-east, the union territories, Jammu & Kashmir and Ladakh. This is a
      JSON edit with no code change, it is the single cheapest thing that moves
      Depth & Reach Across India, and the coverage view already renders it. A
      judge asking "does this work outside Delhi" gets a list rather than an
      assurance.

- [ ] **Forecasting.** The brief names it, nothing in the system does it, and
      25% of the score is AI / Technical Execution. Vertex AI would be the
      obvious tool and is excluded by the free-tier constraint, so the version
      being built is: Open-Meteo's forecast endpoint for the next 72 hours,
      OpenAQ's recent history for the location, and the cluster's own report
      history, joined by a Gemini call with structured output into a risk
      window with a stated confidence and the reasoning that produced it.

      This is a model reasoning over real data, not a trained predictor, and it
      must be labelled as exactly that in the interface and in the deck. An
      overclaimed forecast is worse than an honest one — a judge who finds the
      label has learned the project is careful, and a judge who finds the
      overclaim has learned the opposite.

- [ ] **Interoperability, stated concretely.** The non-goal is reversed because
      40% of the score rests on it. What is *not* being built is federated model
      training, which cannot be demonstrated in sixteen days and could not be
      seen if it were. What is being built is the part a second state could
      actually use: the authority table as a documented, versioned open data
      file another instance can fork and extend; the public register at
      `GET /register` as a documented open endpoint with a published schema, so
      two instances can read each other's confirmed cases; and a page in
      `docs/` stating precisely what a second state has to do to stand up its
      own instance. Interoperability as a described and demonstrated data
      contract, which is what "designed as a digital public good" means in
      practice.

- [ ] **Submission package.** Public repo (already), a 3–5 minute end-to-end
      demo video, a 10–12 slide deck covering problem, solution, AI approach,
      who it serves, deployability and national scale, a 2–3 line description,
      and the deployed link. The deck and the video are not overhead — under
      these weights they are where Deployability and Impact are actually
      argued, and they need days, not the last evening.

## Under consideration, not yet committed

- **ISRO / Bhuvan or Earth Engine imagery.** The organisers name both and the
  brief says "satellite imagery", which FIRMS detections are not. Earth Engine
  is free on a noncommercial registration. Genuine depth if it lands; a rabbit
  hole if it does not, and v0.1 already called it one. Decide by day four or
  drop it.

- **CPCB / data.gov.in station data alongside OpenAQ.** More India-specific than
  OpenAQ and named by the organisers as a source, which is worth something under
  Problem-Solution Fit. Cheap if the endpoint behaves.

- **Multilingual interface.** The complaint is already drafted in the region's
  language, which is the part with legal weight. Translating the interface
  chrome is a larger job for a smaller gain, and the build requirement asks for
  multilingual support "where the track calls for it" — track 02 does not, track
  01 does.

## Still out of scope

Every non-goal from v0.1 and v0.2 stands unless listed above, and three are
worth restating because the new brief will be read as inviting them.

**Voice intake.** Cloud Speech-to-Text needs a billing account, and track 02
does not ask for voice. Track 01 does; we are not entering track 01.

**Federated model training.** Reversed only as far as the data contract above.
Actually training or exchanging models across instances is not happening in
sixteen days, and claiming it in a deck without building it is the kind of thing
that loses a project more than it gains.

**A real delivery transport, automatic escalation, and naming a responsible
party.** Safety properties. The brief's "alert relevant authorities" does not
change them.

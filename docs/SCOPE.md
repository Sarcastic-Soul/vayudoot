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
- [ ] One real end-to-end run against a real photograph, start to finish —
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
- [ ] Deployed on a public URL, free tier, no credit card — `Dockerfile` is
      written and the image runs; the Space itself is not up yet
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

- [ ] **Case lifecycle.** `ACKNOWLEDGED` and `RESOLVED` existed in the status
      enum with nothing able to set them, so "track and escalate" was half true:
      a case could be filed and escalated but never recorded as answered or
      settled, and `escalation_due()` kept reporting an answered case as overdue.
      Adds acknowledge, resolve and withdraw, and makes the escalation clock
      respect them. This is not a new feature; it is an unfinished one.

- [ ] **Rate limiting and upload caps.** `POST /reports` is open and each report
      spends roughly ten metered model calls from a free tier. On a public URL
      one crawler empties the day's budget. The upload path also reads an
      unbounded body into memory before decoding it. Both are prerequisites for
      the public deployment that was already in scope.

## New capability

- [ ] **Prompt evaluation harness.** The corroboration stage has been wrong twice
      — once discarding its own structured output, once inventing corroboration
      from a wind bearing — and both times only a live run caught it. Prompts are
      now being edited regularly with no way to tell whether a change helped.
      A fixture set with expected classifications, scored for accuracy and
      confidence calibration, is what makes every other change safe.

- [ ] **Clustering repeat reports.** Fifteen reports at one location over a month
      is a categorically stronger complaint than one, and a pattern is the
      argument a regulator actually acts on. Uses only data already stored and
      needs no new external API.

- [ ] **RTI follow-up drafting.** When the statutory window lapses, an Indian
      citizen's real lever is not a second email — it is a Right to Information
      application asking what action was taken. This is the most India-specific
      thing the project can do, and it turns escalation from repetition into
      something with legal weight.

- [ ] **Evidence pack.** One document carrying the photograph, the corroboration
      data, the map, the complaint and the timeline — something that can be
      attached, printed, or handed to a journalist or an NGO.

- [ ] **Public case register.** Cases are already deep-linkable; making one
      shareable read-only turns individual complaints into a visible record,
      which is where most of the accountability value lives.

- [ ] **Multiple photographs per report.** One angle is often not enough to
      classify confidently, and the confidence floor then halts a real event.

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

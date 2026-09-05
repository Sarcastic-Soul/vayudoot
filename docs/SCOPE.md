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

### Delivery
- [ ] Deployed on a public URL, free tier, no credit card — `Dockerfile` is
      written and the image runs; the Space itself is not up yet
- [x] Frontend served by the same FastAPI process, so there is one deployment
- [x] `README.md` and `docs/architecture.md` accurate to what actually ships
- [x] Architecture diagram as an image, not only the ASCII sketch

### Data
- [x] Authority table covering enough regions for the demo location to resolve
      to a specific authority rather than the generic fallback

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

## Rules for changing this file

Moving something from out-of-scope to in-scope is a decision, not a drive-by
edit. Write down why in `BUILD-LOG.md` when you do it.

Adding something that appears on neither list means it was never considered.
Consider it first.

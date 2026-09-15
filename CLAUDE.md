# Vayudoot — working agreement

Read this before changing anything. It records decisions that are already made,
so they do not get relitigated or quietly undone.

## What this is

A hyper-local pollution detection network in which citizen reports are one class
of sensor. It joins citizen photographs to satellite thermal detections, ground
station readings and meteorology to find pollution events that macro-level
monitoring misses, forecasts where air quality is about to degrade, and hands
the relevant authority a corroborated case it can act on — drafted, jurisdiction
resolved, and tracked if it is filed.

**The unit of work is a hotspot, not a case.** That sentence is the product
decision the whole design turns on, and it is recent: through v0.2 the unit of
work was one citizen's complaint, and the system was a complaint desk that
collected data along the way. `docs/SCOPE.md` under v0.3 records why that point
of view was wrong and what it changed. Complaint drafting, filing and RTI are
retained and are still the strongest thing the project does — they are now one
of the *actions* available from a detection rather than the purpose of the
system.

A hotspot does not need a citizen report to exist. Satellite and station
evidence seed hotspots on their own; a citizen photograph upgrades one. If you
find yourself writing code that assumes otherwise, read the v0.3 section before
continuing.

Built on the Strands Agents SDK. See `README.md` for the user-facing description
and `docs/architecture.md` for how the pieces fit and why.

## Hard constraints

These are not preferences. Breaking one is a bug.

### 1. Nothing may reach a real regulator

Live filing raises rather than sends, and no delivery transport is wired in on
purpose. Every committed authority email is on the reserved `.invalid` TLD.
Authority *names* are real and public; addresses are not. `tests/test_filing_safety.py`
asserts both. Do not "finish" the filing transport, do not put a real address in
`authorities.example.json`, and do not weaken those tests.

### 2. A human confirms before anything is filed

The pipeline stops at `AWAITING_CONFIRMATION`. Filing happens only through
`POST /cases/{id}/confirm`. Do not make the pipeline file automatically, however
convenient it looks in a demo.

### 3. Free tier only

Every dependency must be usable on a free tier without a credit card, or must
already be paid for. See `docs/deployment.md` for what is chosen and why. Do not
introduce a service that bills, needs a card on file, or has a trial that expires.
If something genuinely needs paid infrastructure, say so and stop rather than
signing up.

### 4. Stay inside scope

`docs/SCOPE.md` lists what v0.1 is and, more importantly, what it is not. The
non-goals are there because the schedule is short, not because the ideas are bad.
Do not build them. If a change does not serve a listed in-scope item, ask first.

### 5. Inference is the only running cost — treat it that way

Models come in two tiers, selected by `build_model(tier=...)`:

- `primary` — judgement: reading a photograph, drafting a legal complaint
- `fast` — mechanical: call one tool, summarise the output

The corroboration graph runs three agents in parallel and each only calls a tool
and summarises. Those, the graph's synthesis node, and the jurisdiction agent are
on `fast` deliberately. Do not promote them to `primary` without a reason you can
state.

Two agents are on `primary` inside a report run: evidence, which reads the
photograph, and drafting, which writes the complaint. The other eight calls a
report makes are all `fast`. Adding a third primary agent to that run raises the
expensive count by half, so it needs a reason.

RTI is the third agent on `primary`, and it is outside that count on purpose. It
drafts a statutory application to a Public Information Officer — the same class
of legal writing as the complaint, and wrong in the same way if it is sloppy —
but it runs only when a citizen asks for one after a statutory window has
lapsed, which is rare and never part of the ten calls a report spends. Forecast
is on `fast` despite also running outside a report, because it summarises tool
output rather than composing a document.

**The two tiers can sit on different providers.** `VAYUDOOT_MODEL_PROVIDER_FAST`
overrides the provider for the fast tier only, and `settings.provider_for(tier)`
is the single thing that decides. That is deliberate, not incidental: it spreads
one report across two free tiers, putting the eight mechanical calls where the
request allowance is and the two judgement calls where the better model is. Keep
`build_model()` as the only place a provider is constructed, and keep the
decision in `provider_for()`.

### 6. Google AI is mandatory, and it is a rule, not a preference

The target is the Build with AI: Code for Communities hackathon, problem
statement 02. Its first rule is that a submission without Google AI integration
is not considered. The shipped configuration therefore puts **both** tiers on
Gemini — primary on flash, fast on flash-lite.

This narrows constraint 5 without cancelling it. The tier split survives as a
cost control inside one provider; what does not survive is shipping with the two
judgement calls on Ollama, because that puts the only inference a judge would
call meaningful on a non-Google model. Ollama stays a supported provider for
local development and the offline test suite, and `build_model()` stays the only
place a provider is constructed — a system a state could run on its own
hardware is part of the deployability argument, so the abstraction earns its
keep.

Free tier still binds, and it decides which Google services are available:
Gemini via AI Studio, BigQuery sandbox, Firebase Spark and Earth Engine
noncommercial need no card. Vertex AI, Cloud Run, Maps Platform, Speech-to-Text
and Translation all need a billing account and are therefore out. See
`docs/SCOPE.md` under v0.3.

### 7. A hotspot is a public claim about a place. Treat it as one

Through v0.2 the system's output was a private complaint to an authority. It is
now a public map of where pollution is happening, plus a forecast of where it is
about to happen. That is a different class of harm, and three rules follow.

**Area granularity, never a point on a building.** A tightly drawn hotspot
around one facility is a public accusation against an identifiable operator even
though no name appears anywhere. Hotspots carry a minimum radius, render as an
area, and always display their confidence. Constraint 4's non-goal — never
naming a responsible party — is sharper here, not softer.

**Corroboration gates publication.** A hotspot's confidence is capped unless
independent evidence agrees with the citizen reports. Without this, coordinated
false reporting manufactures a hotspot, and the map becomes a weapon. The
corroboration graph already produces the agreement; it must gate the hotspot,
not merely annotate it.

**A forecast is a model's reasoning, never an official advisory.** Everything
predictive is labelled as model-derived, shows the inputs it reasoned over, and
states conditions rather than instructions. It must never present itself as, or
be confusable with, a CPCB or IMD forecast. People act on air quality
predictions — that is the point of making them — so an unlabelled wrong one does
real harm to real lungs.

## Conventions

- **Never construct a model provider directly.** Call `models.build_model()`. It
  is the only place a provider is instantiated, which is what lets the whole
  system move between Gemini and Ollama with one environment variable.
- **Stages hand each other typed objects**, not free text. Every stage returns a
  Pydantic model from `schemas.py` via Strands structured output. If you add a
  stage, give it a schema.
- **Tools return plain dicts and never raise.** A failed API call comes back as
  `{"error": ...}` so the agent can reason about it. Do not let an HTTP error
  crash the pipeline.
- **Jurisdiction data is data.** It lives in `src/vayudoot/data/authorities.example.json`,
  keyed by administrative region. Adding a state is a JSON edit. Do not hardcode
  regions, authorities, or statutes into Python.
- **Prompts live in `agents/prompts.py`**, all of them together, so their tone
  can be reviewed as a set.
- Line length 100, `ruff check .` clean, `pytest` green before any commit.

## Verify, do not remember

The Strands SDK moves quickly. Two things that memory gets wrong:

- Structured output is `agent(prompt, structured_output_model=Model)`. The
  `Agent.structured_output()` method is deprecated.
- Image content blocks use the SDK's Bedrock-shaped envelope, whatever the
  configured provider is:
  `{"image": {"format": "jpeg", "source": {"bytes": ...}}}`.

When unsure about the SDK, read the installed package
(`.venv/bin/python -c "import inspect, strands; ..."`) rather than guessing.

## Commits

The user authors commits alone. Do not add a `Co-Authored-By` trailer or any
generated-with attribution.

## Run agents in parallel

Independent work should be split across agents rather than done in sequence. It
is materially faster, and the constraint that makes it work is file ownership,
not task size.

**One owner per file, per wave.** Two agents editing `api.py` at once produces a
merge, not a speedup. Partition by the files a task must touch, and if two tasks
want the same file, they belong in the same agent or in different waves. The
usual clean split is Python versus `src/vayudoot/web`, since the interface and
the pipeline share nothing.

**Keep shared documents out of every brief.** `CLAUDE.md`, `docs/SCOPE.md` and
`README.md` are written by whoever is coordinating. Several agents editing the
same document concurrently is the one conflict that is guaranteed.

**Agents do not commit.** They leave the work in the tree and report. The
coordinator reads the diff, verifies it independently, and commits — an agent
reporting success is evidence, not proof.

Tell each agent: which paths it owns and which it must not touch; that another
agent is working concurrently, so a test failure in a file it did not touch is
not its problem; and that a dev server it starts is its own to stop, because a
stray one holds the port for everybody afterwards.

For interface work, require rendered screenshots. Every UI bug in this project
so far — invisible nav labels, a clipped control, a single-column layout that
should have been two — passed both `ruff` and `pytest` and was only ever visible
in an image.

## Record decisions where they are enforced

There is no separate decision log. A reason that lives in its own file drifts
away from the thing it justifies and is read by nobody; put it where someone will
hit it while changing the code.

- A constraint that must hold goes in this file, under Hard constraints.
- A choice about how one module behaves goes in that module's docstring or next
  to the line it explains.
- A behaviour that must not regress goes in a test, with the reason in the test's
  docstring.
- Work that is planned, deferred, or deliberately not being done goes in
  `docs/SCOPE.md`.

If a decision fits none of those, it probably did not need writing down.

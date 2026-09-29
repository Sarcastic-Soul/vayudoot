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

Built on Google's Agent Development Kit (ADK) with Gemini. See `README.md` for the user-facing description
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

Imagery is the fourth agent on `primary`, and it is outside that count for the
same reason as RTI. It reads a satellite true-colour snapshot and judges whether
smoke is visible under the cloud — judgement on an image, the evidence stage's
kind of work, which flash-lite does worse. It runs only when an operator asks
about one hotspot, and its reading is cached per hotspot and image date, so the
same picture is never paid for twice. The hotspot alert is on `fast`: the facts
block is built in Python and the model only writes a short summary of it.

Voice is on `fast`. Hearing a voice note and translating it is transcription,
not judgement; the judgement about what the report shows stays with evidence on
`primary`. It adds one fast call to a report that carries a voice note and no
primary call, and flash-lite heard Hindi, Tamil and Portuguese accurately in
live tests.

**The two tiers are two Gemini models, each with its own fallback chain.** AI
Studio meters every model separately, so the eight mechanical calls go where
the request allowance is (flash-lite) and the two judgement calls go where the
better model is (flash). `config.DEFAULT_MODEL_IDS` and `MODEL_FALLBACKS` hold
the choice; keep `build_model()` as the only place a model is constructed.

### 6. Google AI is mandatory, and it is a rule, not a preference

The target is the Build with AI: Code for Communities hackathon, problem
statement 02. Its first rule is that a submission without Google AI integration
is not considered. The shipped configuration therefore puts **both** tiers on
Gemini — primary on flash, fast on flash-lite.

Gemini is the only model provider, and Google's ADK is the agent framework.
Through v0.3 the project ran on the Strands Agents SDK (an AWS project) with
Ollama as a second provider; both were removed so that nothing in the stack is
another cloud company's. Do not add a non-Google model provider or agent
framework back. The offline test suite needs neither: it replaces
`Gemini.generate_content_async` or the whole stage.

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

- **Never construct a model directly.** Call `models.build_model()`. It is the
  only place a model is instantiated, which is where the API key, the tier's
  model id and the fallback chain are decided.
- **Stages go through `models.Agent`**, not ADK's `LlmAgent` directly. It is a
  thin wrapper that runs one question in a fresh in-memory session and hands
  back `result.structured_output`. A multi-agent stage composes
  `Agent.llm_agent()` into an ADK `Workflow` (see `agents/corroboration.py`).
- **Stages hand each other typed objects**, not free text. Every stage returns a
  Pydantic model from `schemas.py` via ADK's `output_schema`. If you add a
  stage, give it a schema.
- **Tools are plain functions** with typed arguments and a docstring; ADK reads
  both to describe the tool to the model. There is no decorator.
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

Google's ADK moves quickly. Things that memory gets wrong:

- A string `instruction` on an `LlmAgent` is a template: ADK fills `{name}` from
  session state and fails on a brace it cannot fill. `models.Agent` always
  passes the instruction as a function, which ADK uses as written.
- `ParallelAgent` and `SequentialAgent` are deprecated in ADK 2 in favour of
  `google.adk.workflow.Workflow`, which takes edges; a `JoinNode` waits for
  every predecessor.
- Images and audio go to the model as `google.genai.types.Part` inline data —
  `models.media_part(data, "image/jpeg")` — not as any SDK-specific envelope.
- On the AI Studio backend ADK cannot pair tools with a native response schema,
  so it gives the model a `set_model_response` tool instead. The answer still
  lands in state under the agent's `output_key`.

When unsure about the SDK, read the installed package
(`.venv/bin/python -c "import inspect, google.adk; ..."`) rather than guessing.

## Commits

The user authors commits alone. Do not add a `Co-Authored-By` trailer or any
generated-with attribution.

## Run agents in parallel

Split independent work across agents. The rule that makes it work is **one owner per file, per
wave** — the usual clean split is Python versus `src/vayudoot/web`. Agents do not commit; the
coordinator reads the diff, verifies independently, and commits. For interface work, require
rendered screenshots — every UI bug here so far passed both `ruff` and `pytest`.

Full briefing rules: `docs/parallel-agents.md`.

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

## UI and design work

Hackathon project — optimize for visual impact, not platform consistency. Full creative latitude
on color, typography, layout, animation and iconography; pick whatever best fits the project theme
without waiting for sign-off. Reach for shadcn/ui, Aceternity UI, Magic UI, Framer Motion and similar
third-party component/animation sources freely — judges and demo viewers see the surface, not the
process.

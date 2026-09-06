# Vayudoot — working agreement

Read this before changing anything. It records decisions that are already made,
so they do not get relitigated or quietly undone.

## What this is

An agent that takes a citizen's photograph of a pollution event and runs the
whole case end to end: classify the photo, corroborate it against independent
evidence, resolve which authority holds jurisdiction, draft the formal complaint,
file it, then track and escalate it when the statutory window lapses.

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

Only two agents are on `primary`: evidence, which reads the photograph, and
drafting, which writes the complaint. The other eight calls a report makes are
all `fast`. Adding a third primary agent raises the expensive count by half, so
it needs a reason.

**The two tiers can sit on different providers.** `VAYUDOOT_MODEL_PROVIDER_FAST`
overrides the provider for the fast tier only, and `settings.provider_for(tier)`
is the single thing that decides. That is deliberate, not incidental: it spreads
one report across two free tiers, putting the eight mechanical calls where the
request allowance is and the two judgement calls where the better model is. Keep
`build_model()` as the only place a provider is constructed, and keep the
decision in `provider_for()`.

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

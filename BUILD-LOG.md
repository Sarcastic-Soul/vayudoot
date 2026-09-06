# Build log

An append-only record of decisions and the reasoning behind them, so that a
choice made once does not get quietly undone later. Newest entries at the bottom.

Entries are about the engineering: what was decided, what turned out to be wrong,
and what was learned.

---

## 6 September 2026 — Day 0

**Chose the problem.** A pollution complaint agent over an agricultural advisory
agent. Both address environmental harm, but advisory systems are chat: they hand
a person information and leave the work to them. The work here — identifying the
authority, drafting in the right register, filing, chasing a statutory deadline —
is tedious, repetitive, and the actual reason people give up. Automating it
changes an outcome rather than informing one.

**Read the SDK instead of trusting memory.** Installed `strands-agents` and
inspected the package directly for the image content block shape and the
`Agent.__call__` signature. Two things would have been wrong from memory:
structured output is now a `structured_output_model` parameter on the call rather
than the deprecated `Agent.structured_output()` method, and image blocks are
Bedrock-shaped — `{"image": {"format": ..., "source": {"bytes": ...}}}`.

Generalising: this SDK moves fast enough that its API is not something to
remember. Read the installed package.

**Used a graph only where the problem has a fan-out.** The first instinct was to
make the entire pipeline a `GraphBuilder` graph, because multi-agent graphs are
the SDK's headline feature. That would have been decoration. Classification must
precede corroboration — you cannot corroborate a claim before knowing what is
claimed — and jurisdiction must precede drafting, because the statute cited
depends on the authority. Those are real dependencies and belong in a pipeline.

The one genuine fan-out is corroboration: satellite detections, ground station
readings, and wind data are independent, and none needs another's output. Only
that stage is a graph. Reaching for the impressive abstraction where the problem
does not have that shape produces something that looks sophisticated and runs
worse.

**Made filing safety a tested property rather than a documented intention.** The
obvious catastrophic failure for this project is sending a complaint to a real
pollution control board from a debugging run. Documentation does not prevent
that. So: live filing raises rather than sends, no transport is wired in, every
committed authority email is on the reserved `.invalid` TLD, and a test walks the
JSON and asserts it. Authority names are real and public; addresses are not.

**Put a confidence floor in front of the complaint.** The evidence stage returns
an explicit confidence, and below 0.55 the pipeline halts with status `rejected`
rather than proceeding. This stage's output eventually becomes a formal complaint
about a real location, so an honest refusal is worth more than a confident guess.
The drafting prompt carries the same principle: no naming an accused party, no
claiming certainty the evidence does not support.

**Split models into two tiers.** Inference is the only real running cost. A
single report is six agent invocations, and four of them do nothing but call one
tool and summarise the result. Running those on the same model that reads
photographs and drafts legal text multiplies the cost of every report for no gain
in quality. `build_model(tier="fast")` covers the corroboration graph and the
jurisdiction agent; the primary tier is reserved for judgement.

**Wrote the scope's non-goals down before building the interface.** `docs/SCOPE.md`
lists more things that are not being built than things that are. The failure mode
for a project on a short schedule is a wide demo where nothing works end to end,
and the defence against it is deciding the boundary in advance, while it is still
cheap to say no.

**Kept the project independent of any one venue.** Deadlines, submission
requirements, and judging criteria live outside this repository. What is inside
is the system and the reasoning. This is partly hygiene and partly practical:
constraints borrowed from a specific deadline age badly, and a codebase organised
around one is hard to point anywhere else.

## 6 September 2026 — Day 0, evening

**Split `status` from `stage`.** The interface has to show something during the
two minutes a case spends being processed, and the case's legal status is
`draft` for that entire time. Overloading `status` with `running_corroboration`
would have mixed a lifecycle that matters legally with a progress bar that does
not. So `Case` now carries both: `status` for where the case stands, `stage` for
where the machinery is. The pipeline saves after every stage, so a poller reads
partial state from disk the moment it exists rather than waiting for the run to
finish.

**Made `POST /reports` return before the run finishes.** A full run is minutes of
model calls. The endpoint now writes the case, spawns the pipeline as a
background task, and answers `202` with a case id; the page polls. The tasks are
held in a module-level set because `asyncio` keeps only a weak reference to a
running task, and an unreferenced task can be collected mid-run — which would
have shown up as cases that silently stop advancing, on a free container, under
load, and nowhere else.

**A stage that raises leaves a readable case.** The whole run is wrapped, and a
failure sets `status=failed` with the exception recorded on the case, and leaves
`stage` on whatever was running when it died. There is deliberately no `failed`
stage: overwriting the stage with `failed` would have thrown away the one fact
worth keeping. Losing a run to a transient FIRMS timeout is acceptable; losing
the evidence of where it died is not.

**Tested the pipeline without a model.** `tests/fakes.py` replaces the four agent
stages with deterministic ones, so ordering, checkpointing, the confidence floor,
and the failure path are all exercised offline in half a second. The suite went
from 12 tests to 32 and still needs no credentials, which is what makes it
runnable on every commit rather than only when someone has keys loaded.

**Kept the frontend inside the Python package.** `src/vayudoot/web/` — three
static files, no build step, no bundler, no second deployment. Mounted last so it
cannot shadow an API route. Two endpoints exist only for it: the photograph, and
the filed envelope as written to the outbox. The envelope one matters for the
demo: the claim is not "it would have sent something", it is "here is exactly
what it would have sent".

**Caught a packaging regression the tests could not see.** Adding `data/` to
`.gitignore` — meant for the runtime case directory — also excluded
`src/vayudoot/data/authorities.example.json` from the built wheel, because
Hatchling honours VCS ignore patterns. Every test passed; a container build would
have shipped a jurisdiction lookup with no table in it. Narrowed the pattern to
`/data/` and verified by listing the wheel's contents, then by running the built
image and asking it to resolve an authority.

**Verified the deployment target rather than assuming it.** Built the image, ran
it, checked `/health`, the interface, and a jurisdiction lookup from inside the
container. The Dockerfile runs as uid 1000 on port 7860 because that is what
Hugging Face Spaces expects.

**Widened the authority table to 24 states and union territories.** Names are
real and public; all 107 addresses remain on `.invalid`. The generic fallback is
still there, and the agent is still told to say when it landed on it.

## Day 1 — dropped the Anthropic provider

**Removed the direct Anthropic provider entirely.** It is off the table for this
project, so it should not sit in the code as a half-supported option that nobody
will ever exercise. Gone from the `Provider` literal, `DEFAULT_MODEL_IDS`,
`build_model()`, `Settings.anthropic_api_key`, `.env.example`, the README, and
the `strands-agents` extras. Three providers remain: Bedrock, Gemini, Ollama.

**Changed the Bedrock defaults too.** They pointed at Claude models, which meant
"do not use Claude" was not satisfied by deleting the direct provider alone.
Bedrock now defaults to `us.amazon.nova-pro-v1:0` for the primary tier and
`us.amazon.nova-lite-v1:0` for the fast tier. Both are multimodal, which the
evidence stage needs, and both are Amazon's own models rather than a rebadged
third party. `VAYUDOOT_MODEL_ID` still overrides either tier, so nothing is
locked in.

The provider abstraction earned itself here: removing one of four providers
touched exactly one branch in `models.py` and one table in `config.py`. No agent,
stage, or tool changed. Suite still 32 passing, ruff clean.

## Day 1 — first live run, and what it caught

**Gemini 2.5 is gone for new API keys.** `gemini-2.5-flash-lite` returned a 404
saying the model "is no longer available to new users". Listed what the key can
actually reach and moved the defaults to `gemini-3.5-flash` (primary) and
`gemini-3.5-flash-lite` (fast). Both tiers answered on the first try afterwards.

**The corroboration graph was silently discarding its own output.** `corroborate()`
read `structured_output` off the `NodeResult`, but a graph node wraps an
`AgentResult` rather than forwarding its attributes, so the attribute was always
absent and every real run fell through to the empty "graph returned no structured
synthesis" fallback. Satellite, ground station and meteorology all did their work;
the synthesis agent produced a complete `Corroboration`; the pipeline threw it
away and drafted complaints with no corroborating evidence in them.

Nothing in the suite could see this, because the pipeline tests replace the whole
stage with a fake. That is the right trade for testing control flow offline, but
it leaves the seam between the SDK and this code untested. `_synthesis_output()`
now reaches through to `node.result.structured_output`, falls back to the node's
agent results, and `tests/test_corroboration_graph.py` pins both shapes with
stubs. Suite is 36.

The lesson is the one already written at the top of `CLAUDE.md`: verify against
the installed SDK rather than assuming an attribute is where it reads like it
should be. The fallback made it worse by being plausible — a wrong answer that
looks like a legitimate "no evidence found" result is harder to notice than a
crash.

**Everything else answered on the first live run.** All four evidence tools
returned real data for Delhi: FIRMS, OpenAQ (nearest CPCB station 16.87 km),
Open-Meteo wind with the upwind back-trace, and Nominatim. Jurisdiction resolved
to the New Delhi Municipal Council under Rule 15 with a 15-day window, and the
drafting stage produced a properly addressed complaint in English and Hindi.

The evidence stage was exercised with a synthetic image, and correctly refused
it: `unclear`, confidence 0.10, reasoning that it is an illustration rather than
a photograph. The pipeline then halted at the 0.55 floor, which is the whole
point of the floor. A real photograph is still the one thing untested.

## Day 1 — the Gemini free tier is a request budget, not a rate limit

The daily caps are 20 requests on the flash tier and 500 on flash-lite, with the
pro models paid. That reframes the two-tier split: it is not about cost per token
any more, it is about how many reports a day the thing can run at all.

The split as built put three agents on primary — evidence, drafting, and the
corroboration graph's synthesis node — which is six reports a day. Moved
synthesis to the fast tier: it merges three summaries the source agents already
wrote, reads no image, and calls no tool, so it is the one primary call that was
not buying judgement. Two primary calls a report, ten reports a day.

Evidence and drafting stay on primary and should. One reads a photograph and the
other writes the document that a regulator reads; those are the two places where
model quality is visible in the output.

Recorded the budget in `CLAUDE.md` next to the tier rule, so the next person to
reach for `primary` knows it costs three reports a day.

## Day 1 — checked the free tiers properly instead of assuming

Two assumptions turned out wrong, and both mattered.

**Groq's free tier has no vision model.** The published list is gpt-oss-120b/20b,
qwen3-27b, compound, prompt-guard, whisper, orpheus — nothing that reads an
image. So Groq cannot serve the evidence stage at all, which was the premise of
putting it anywhere useful. Its limits are also throughput rather than context:
30 RPM, 1000 RPD, 8K tokens per minute, 200K per day. The 8K is a per-minute
meter, not a context window, and the three corroboration agents fire in parallel
with tool payloads, so the fast tier is the one placement that would actually hit
it. Left Groq out.

**Ollama Cloud's free tier can serve everything.** `gemma4:31b` is multimodal
with a 256K context, which makes it the only free option that covers the
evidence stage as well as drafting. It needed no new provider — the `ollama`
branch already existed, and hosted Ollama differs from a local daemon only by
host and a bearer token. Added `OLLAMA_API_KEY`, passed through
`ollama_client_args` as an Authorization header, and only when a key is set,
because sending an empty one breaks a local daemon.

Changed the Ollama defaults from `llama3.2` to `gemma4:31b` and `gpt-oss:20b`.
A laptop that cannot host a vision model is the common case here, so defaulting
to local model ids optimised for the setup nobody in this project has. Running
locally is still one host and two model ids away.

The free quota is published as session and weekly percentages rather than
request counts, so unlike Gemini there is no arithmetic to do in advance — watch
the meter.

## Day 1 — down to two providers

Removed Amazon Bedrock. It bills, and constraint 3 says a dependency must be
free or already paid for, so it was never really eligible; it survived this long
because it was written before that constraint had teeth. Gone from the `Provider`
literal, the default model table, `build_model()`, `Settings.aws_region`,
`.env.example`, and the docs. The default provider is now `gemini`, which is
what the project actually runs on.

**Local Ollama was not a separate thing to remove.** Local and cloud are the same
`ollama` branch — the difference is a host and a bearer token, which is why
adding cloud support needed no new provider in the first place. What did change
is the default host, from `http://localhost:11434` to `https://ollama.com`. The
old default optimised for a machine with a GPU to spare, which is not the setup
this project has. Local is still one environment variable away, and is still
documented.

Note that dropping the branch does not drop a dependency: `BedrockModel` lives in
the base `strands-agents` package, so boto3 comes along regardless. This was
about removing an option nobody can use, not about shrinking the install.

Two providers left, both free tiers with no card:

- `gemini` — verified end to end against live APIs, ~10 reports a day
- `ollama` — Ollama Cloud, `gemma4:31b` for vision, quota published as opaque
  percentages, not yet exercised against a real key

## Day 1 — one report, two free tiers

Verified Ollama Cloud against a real key, stage by stage: connectivity, a tool
call with structured output on `gpt-oss:20b`, vision on `gemma4:31b`, the
parallel corroboration graph, bilingual drafting, and a full pipeline run from
Mumbai coordinates through to a sandbox envelope. `gemma4:31b` refused the
synthetic test image for the same reason Gemini did — that it is an illustration
rather than a photograph — which is the judgement the confidence floor depends
on, so both providers are usable for the evidence stage.

Then split the tiers across both providers rather than loading one. Ollama's free
quota is published as opaque session and weekly percentages, so putting all ten
calls a report through it spends a budget nobody can measure. Gemini's is
published precisely and the shape is lopsided: 20 requests a day on flash, 500 on
flash-lite. The console also showed flash-lite hitting 15/15 RPM during testing —
the three corroboration agents fire in parallel, so the per-minute ceiling is a
real constraint, not just the daily one.

`VAYUDOOT_MODEL_PROVIDER_FAST` now overrides the provider for the fast tier
alone, resolved by `settings.provider_for(tier)`. `build_model()` is still the
only place a provider is constructed; the tier abstraction grew a second
dimension rather than being worked around.

Shipped configuration is primary on Ollama Cloud, fast on Gemini flash-lite. Two
calls a report against the opaque budget, eight against the 500-a-day one, and
Gemini's scarce 20-a-day flash tier goes entirely unused. Verified live from
Bengaluru coordinates: BBMP resolved as the authority and the complaint drafted
in Kannada, which is the local-language resolution working as well.

The trap this creates is quiet, so it has tests: reading fast model ids out of
the primary provider's table would still produce a working agent, just the wrong
one. `tests/test_models.py` pins that.

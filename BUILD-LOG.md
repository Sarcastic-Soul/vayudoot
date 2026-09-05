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

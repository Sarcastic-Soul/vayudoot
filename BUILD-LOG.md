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

## Day 1 — the first real photograph, and the bug it exposed

Ran a real photograph of a plant with two active stacks through the whole
pipeline from the browser. Everything mechanical worked: classified as
`industrial_emission` with accurate visible indicators, reverse geocoded to
Atal Nagar-Nava Raipur, resolved to the Chhattisgarh Environment Conservation
Board under Section 31A of the Air Act with a 30-day window escalating to the
CPCB, drafted in English and Hindi, filed to the sandbox outbox.

Two things were wrong, and one of them mattered.

**The corroboration stage reported `corroborated: true` on no evidence.** The
satellite found nothing. The nearest station was 24.89 km away reporting normal
levels — which is closer to evidence against than for. The only thing left was a
wind bearing, and the synthesis agent used it to conclude there was "active
transport from a west-southwest upwind source direction where industrial
infrastructure is present". There is no tool in this project that can see whether
industrial infrastructure is present anywhere. It made that up.

The prompt invited it: "corroborated means at least one independent source is
consistent with the reported event". Wind is consistent with every report ever
filed, because wind always blows in some direction. Rewrote the definition to
require a positive sensor reading — a satellite thermal detection, or a station
reporting elevated levels of a pollutant the event would produce — and said
explicitly that meteorology alone is never corroboration, that a normal reading
is not corroboration at whatever distance, and that the agent may state where the
upwind point is but not what is there. Tightened the schema description to match,
since that is what the model actually sees for the field.

Re-ran the same coordinates: `corroborated: false`, with notes that explain what
each source returned and why a hyper-local industrial plume escapes all three.
That is the honest answer, and it was available all along.

This is the second time the corroboration stage has been the weak point, after
the `NodeResult` unwrapping bug. It is the stage with the most room to be
plausibly wrong, because a fabricated corroboration reads exactly like a real
one. Worth remembering when reviewing its output.

**Confidence came back as 1.00.** No classifier looking at a photograph out of
context should be certain, and a 1.0 makes the 0.55 floor meaningless — nothing
that always answers 1.0 can discriminate. Told the evidence prompt that
confidence is a calibrated estimate rather than a rating of the photograph, that
0.9 and up means unambiguous, and that 1.0 is not a valid answer, with the reason:
a photograph cannot tell you what is burning, whether an emission is permitted, or
whether a white plume is smoke rather than steam. The same photograph now returns
0.95, which is a defensible number for two stacks visibly emitting.

## Day 1 — decoding photographs instead of trusting their names

Model content blocks accept four image formats. Phones do not limit themselves to
four: iOS produces HEIC by default, and uploads arrive as TIFF, BMP, screenshots,
and whatever else a camera app emitted.

The old code read the file extension, mapped five suffixes, and rewrote anything
else to `.jpg`. That is the worst possible handling, because it fails silently. An
iPhone photograph would be stored as `.jpg`, handed to the model labelled JPEG
with HEIC bytes inside, and the model would see nothing — while the case carried
on as though a photograph had been read. Nobody would have noticed until the
classifications looked strange.

`images.py` now decodes the bytes to decide the format, converts anything outside
the four into JPEG or PNG, and only falls back to a suffix as a storage detail.
Added Pillow and pillow-heif, and verified a real 3024x4032 HEIC converts to a
1176x1568 JPEG.

Two things came along with it that are not really about formats:

**EXIF rotation is applied to the pixels.** A phone stores the sensor's
orientation in a tag and expects the viewer to rotate. A model reads pixels, not
tags, so a portrait photograph was arriving on its side. This is a classification
bug that would have been invisible in testing, because every test image so far
was made programmatically and had no orientation tag.

**The longest edge is capped at 1568 pixels.** A 12 megapixel photograph carries
far more detail than a classification uses, and the excess is tokens spent for
nothing. With inference as the only running cost and both providers on free
tiers, that is worth the two lines. Images already small enough pass through byte
for byte rather than being re-encoded.

Unreadable bytes are now a 415 at the API boundary rather than a stage failure
four seconds later.

**The old test PNG was invalid.** A handcrafted 1x1 byte string that Pillow
refuses to decode, which only surfaced once something actually decoded it — the
previous code never looked inside the file. Seven API tests failed on the first
run of the new code, and every one of them was the fixture being wrong rather
than the code. Tests now generate real images.

**On AVIF specifically:** already worked, because the supported set is not a list.
Pillow 12 decodes AVIF natively, so it needed no code — which is the argument for
decoding over enumerating. Anything Pillow reads is accepted, roughly seventy
extensions including AVIF, HEIC, TIFF, BMP, JPEG 2000, ICO and PSD. Added AVIF,
JPEG 2000 and a real HEIC to the parametrised tests, and confirmed all of them
inside the built container rather than only in the development virtualenv, since
pillow-heif and the AVIF decoder both depend on bundled native libraries.

## Day 1 — coordinates are not a human unit, and coverage is not a secret

Three fixes, all from the same review: the system was asking for things people do
not know, and hiding things they need to.

**The location field asked for latitude and longitude.** Two number inputs, and a
map that was `hidden` until you pressed "Use my location" — so the default state
of the form was two empty boxes nobody can fill. The map is now the input. It is
present on load, geolocation moves the pin if the citizen allows it, a place
search moves it if they do not, and dragging or tapping always works. Latitude
and longitude became hidden fields the map writes into, and what is shown is the
reverse-geocoded address. Added `GET /geocode` for both directions, since the
address previously only existed server-side, mid-pipeline.

The place search is debounced at 450 ms because Nominatim asks for at most one
request a second and this is their free service.

**The authority fallback was invisible.** If a category called for a municipal
body and the city was not in the table, `lookup_authority` quietly reassigned the
tier to `state` and returned the state board. Nothing downstream could tell that
apart from a real match. A generic state board for an unknown region looked
identical to a named authority for a known one.

The tool now returns `coverage` — `exact`, `fallback`, `generic` — and a note
explaining it. The `Jurisdiction` schema carries both, the prompt says to copy
them and never to upgrade a fallback, and the case shows a warning for anything
that is not exact. But asking a model to report its own accuracy is worth
something, not everything, so the pipeline also checks the one thing that is
deterministic: an email that only exists in the fallback entry means the region
was absent, whatever the agent claimed.

**The table itself is now published.** `GET /authorities` and a Coverage tab
listing all 24 regions, 57 municipal bodies, the category-to-statute rules, and a
plain statement that every address is a `.invalid` placeholder. Jurisdiction is
resolved from a fixed table, so the table's edges are the system's edges, and a
citizen should be able to see that before submitting rather than infer it from a
case that quietly resolved to a placeholder. Publishing the addresses is also how
the safety claim gets checked instead of trusted.

**Still open:** vehicle emission routes to the state pollution control board while
citing Motor Vehicles Act Section 190(2), which that board has no power to
enforce. That is a legal call about which authority is right, not a bug in the
lookup, and it is waiting on a decision.

## Day 1 — one grid, three shapes

Reworked the interface shell. The navigation was three tabs under the header,
which wasted the width on anything bigger than a phone and gave the content a
720px cap regardless of screen.

It is now a single grid whose only variable is where the navigation sits: a bar
under the thumb below 700px, an icon rail to 1080px, a labelled sidebar above
that. One layout to reason about instead of three, and the content area grows to
1080px with real two-column arrangements rather than a wider single column — the
report form splits into "what and where" against "what to say", and a case puts
the photograph and timeline beside the complaint, which sticks while the evidence
scrolls. A line of body text is capped at 72 characters wherever it is prose,
because a complaint is harder to read at 130 characters than at 70.

Two-column placement was done with `nth-of-type` at first and it was wrong: the
columns have different numbers of rows, so grid left holes and pushed the contact
field halfway down the page. Explicit column wrappers instead. Caught it by
rendering the page at 390, 834 and 1440 and looking at it, which is the only way
this kind of bug shows up — nothing about it fails a test.

**Themes are three-state.** Light, dark, or follow the system, remembered in
`localStorage`, applied as `data-theme` on the root. "System" is the default and
a real choice rather than the absence of one. Every colour was already a token;
they are now declared once for light, re-declared under
`prefers-color-scheme: dark` guarded against an explicit light choice, and again
under `[data-theme="dark"]` so an explicit choice wins in both directions.

**Accessibility, beyond the theme.** A skip link. The navigation is a `nav` with
`aria-current` rather than a tablist, because these are sections of a page and
not tabs of a widget. The case status is an `aria-live` region, so a stage
advancing during polling is announced instead of silently changing. Sections are
addressable — `#cases`, `#coverage`, `#VD-XXXXXXXX` — which makes the back button
work and a view linkable. Touch targets are 52px in the phone bar.
`prefers-reduced-motion` now cancels every animation rather than just the one
pulsing dot, and `prefers-contrast: more` promotes the border and secondary text
colours.

## Day 1 — the coverage page was a data dump

Rebuilt it around the question a citizen actually has, which is "what happens if
I report from here", not "here are some rows".

The counts come first as three tiles. The category rules became cards that read
as sentences — "open waste burning goes to the city's municipal corporation,
under Solid Waste Management Rules 2016 Rule 15, 15 days to respond" — instead of
four columns of terse cells; the question is what happens to a kind of report,
not how the rows compare. Region cards carry a chip saying how many cities are
listed, and a footer stating explicitly that anywhere else in that state resolves
to the board above, which is the fallback rule made visible per region rather
than explained once at the top.

The eighty-one placeholder addresses were the loudest thing on the page and the
least useful. They are the evidence for the safety claim, so they stay in the
markup, behind a "Show addresses" toggle. The filter now reports how many regions
matched and has a real empty state that says a missing place still works.

A tile reading "0 states with no city listed" is not information, so when that
number is zero the tile shows the category count instead.

**Three interface changes on top.** The submit disclaimer was removed: the
Sandbox badge in the sidebar says the same thing permanently, and repeating it
under a button is noise. Both maps got an expand control that fills the viewport
and closes on Escape — the Leaflet instance is untouched, only its container
resizes, so the pin does not move. The desktop sidebar collapses to a rail with
the state remembered, animating the grid column rather than jumping.

The collapse control was absolutely positioned at first and rendered underneath
the navigation, invisible. Found it by screenshotting the collapsed state, which
is the only way that class of bug turns up.

## Day 1 — on adopting a frontend framework

Considered and declined for now. The interface is about 1200 lines of plain HTML,
CSS and JavaScript in three files with no build step, which is what lets it ship
as one FastAPI process with no Node in the image. A rewrite buys no capability a
user can see, and the Space is still not deployed.

If it becomes worth doing, the fit is Alpine.js: one CDN script tag, no build,
the single-process deployment survives, and it targets the thing that is actually
unpleasant here — building DOM by concatenating strings into `innerHTML`. Preact
with htm is the same shape at a smaller size. React, Vue and Svelte all need a
build step and Node in the container, which trades the free-tier deployment
property for tooling this size of app does not need. The other direction —
Jinja2, already a dependency, plus htmx — is coherent but a larger rewrite, and
the polling loop is genuinely client state rather than a server render.

## Day 1 — a statute the authority could not enforce

The first vehicle emission case addressed the Chhattisgarh Environment
Conservation Board and cited Motor Vehicles Act Section 190(2). A state pollution
control board has no power under the Motor Vehicles Act — 190(2) is enforced by
the transport authority and the police — so the complaint would have arrived at a
body that could not act on the section it quoted.

Two ways out. Add a transport tier and route there, which is more correct for a
complaint about one identifiable polluting vehicle but costs a schema change and
a transport department entry for all 24 regions, written from memory of
department names. Or align the statute to the authority already being used, which
is one line.

Took the second, and it is not merely the cheaper option. The Air Act has a
provision aimed squarely at this: Section 20, instructions for ensuring standards
for emissions from automobiles, under which the State Government acts in
consultation with the State Board and instructs the vehicle registering
authority. That names the Board's actual role in vehicular emissions, which
Section 19 — air pollution control areas, and the hook used for crop residue
burning — does not.

It also fits what the system can actually see. A photograph of traffic and haze
is an area condition. Section 190(2) targets a specific vehicle being driven,
which a wide shot cannot establish, so citing it was overreaching on the evidence
as well as misdirecting the complaint.

Verified live: a vehicle emission report in Raipur now resolves to the board
under Section 20 with a 30-day window escalating to the CPCB. Pinned with a test
that asserts the category never cites the Motor Vehicles Act again.

## Day 1 — the frontend rewrite, and a grid rule that had been lying about widths

Reversed the earlier decision to leave the interface as plain files. The reason
that entry gave for declining still held right up to the point where the three
files stopped fitting in one head: `app.js` had reached 715 lines and every
render path in it built DOM by concatenating strings into `innerHTML`, guarded
by a hand-rolled `escapeHtml` that had to be remembered at each of its fourteen
call sites. That is the kind of thing that is correct until someone adds a
fifteenth.

Went with the option that entry named as the same shape at a smaller size:
Preact plus htm, as native ES modules with no build step. The runtime is
vendored under `web/vendor/` rather than pulled from a CDN, so the request path
of a page a citizen files a complaint through gains no new third party, and the
single-FastAPI-process deployment is untouched — no Node, no bundler, no
`package.json`. Leaflet stays a CDN `<script>` and is still used through the
global `L`, because it owns its own DOM and must never be re-rendered into.

The layout is now `lib/` for the non-visual parts (fetch wrapper, hash router,
theme, rail, map registry, the polling store), `components/` for sixteen small
components, and `styles/` split seven ways and linked with seven `<link>` tags —
not `@import`, which would serialise the requests. `escapeHtml` is gone: user and
API text is passed as Preact children, so escaping is structural rather than
remembered. The two places that still hand markup to something else are the
Leaflet popups, and those build real DOM nodes rather than strings.

Two behavioural changes fell out of the rewrite rather than being asked for. The
hash is now the single source of truth for the route, set with `pushState`;
before this, opening a case did not touch the hash at all, so a case could not
be linked to and the back button had nothing to walk. And the escalate action
now has a button — the old code had an `act(id, "escalate")` path that no
control could reach. It appears only once the statutory window has actually
lapsed, computed from `filed_at` and `response_window_days`, because the server
refuses it before then and a button that always 409s is worse than no button.

The sidebar collapse was `display: none` below 1080px, so at any narrower window
the feature simply was not there. It now exists from 700px up, wherever there is
a sidebar to collapse, and means one notch narrower each time: the labelled
sidebar becomes a rail, the rail becomes icons alone. Below 700px the nav is a
bar under the thumb and there is nothing to collapse, so no control.

The interesting part was why the control looked broken even at 1080px, where it
was supposed to work. It was being clipped by the sidebar's own edge, and the
cause was not the button at all. `.brand` carried `max-width: var(--page);
margin: 0 auto` from the phone header, and an auto inline margin on a grid item
turns stretching off and sizes the item to fit-content instead — which, with a
`nowrap` tagline inside, was wider than the sidebar. The same rule was on
`main`, which is why the case list at 1440px was rendering as a single narrow
column: it had been sizing itself to its content's max-content width all along,
and its own `repeat(auto-fill, minmax(280px, 1fr))` never had room to produce a
second column. Both fixed by dropping the centring margins where the element is
a grid item and giving `main` an explicit `width: 100%`; the sidebar's implicit
column is now `minmax(0, 1fr)` so an auto track cannot grow past it either.

Found all of that by screenshotting headless Chrome at 390, 760, 834, 900 and
1440 in both themes and looking at the images, and by a throwaway probe page in
the web directory that reported `getBoundingClientRect` for the sidebar parts and
clicked the controls a screenshot cannot — the language toggle, the coverage
filter, the addresses switch, the full-screen map. Worth recording that the
numbers from `--dump-dom` runs are not trustworthy for layout: virtual time does
not advance CSS transitions, so a mid-transition width comes back as the old one,
and the window size is not honoured the way it is for `--screenshot`. The
screenshots are the evidence; the probe only ever pointed at where to look. Both
scratch files were deleted before finishing.

No Python behaviour changed. Starlette already serves `.mjs` as
`text/javascript`, which is what a `type="module"` script requires, so the static
mount needed nothing — verified with `curl -I` rather than assumed. The interface
test now asserts the paths that exist, and a second one asserts the modules come
back with a JavaScript content type, because that failure mode is a blank page
with nothing in the response to explain it.

## Day 1 — reopening the scope, deliberately

v0.1 froze scope hard, and that was right: the failure mode for a project like
this is a broad demo where nothing works end to end. The schedule is no longer
the binding constraint, so `docs/SCOPE.md` gained a v0.2 section rather than
having items quietly added to the v0.1 list. Moving something off the non-goals
list is supposed to be a recorded decision, and there are now eight of them.

Two are not new features at all. The case lifecycle was half-built —
`ACKNOWLEDGED` and `RESOLVED` existed in the enum with nothing able to write
them, so a filed case could never be recorded as answered and `escalation_due()`
would report an answered case as overdue forever. And the API has no rate limit
while every report spends about ten metered model calls from a free tier, which
on a public URL means one crawler ends the day's demo. Both are prerequisites
for the deployment that was already in scope, not additions to it.

Of the six that are genuinely new, the evaluation harness matters most and is
the least visible. Corroboration has now been wrong twice, both times caught by
a live run rather than a test, and prompts are being edited regularly with no
way to tell whether an edit helped. Everything else is easier to justify and
easier to build; this is the one that makes the rest safe.

The three non-goals worth restating are restated in the file, because they are
the ones most likely to be argued for now that there is time: live filing
transport and timed escalation are safety properties rather than missing
features, and identifying the responsible party stays out permanently.

Two agents are running in parallel on the first wave — the lifecycle and
hardening work in Python, and a visual design pass confined to `src/vayudoot/web`.
The file boundary between them is the whole reason they can run at once.
`BUILD-LOG.md`, `SCOPE.md` and `README.md` are excluded from both: an append-only
decision log with three concurrent writers is a merge conflict waiting to
happen, and the decisions are mine to record rather than theirs.

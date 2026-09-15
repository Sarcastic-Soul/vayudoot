# Architecture

The unit of work is a **hotspot**: a place where pollution is happening, drawn as an area,
carrying a confidence and the evidence that produced it. A hotspot needs no citizen report
to exist. A satellite thermal detection or a ground station reading above its standard
raises one on its own, and a citizen photograph *upgrades* one by naming what is actually
burning.

That is the shape of the system, and everything below follows from it. The detection layer
finds hotspots; forecasting says where the air is heading next; federation lets one node
read another's detections. The reporting pipeline — photograph to classified evidence to a
drafted, jurisdiction-resolved complaint — is retained in full and is still the most
India-specific thing here, but it is now **one of the actions available from a detection**
rather than the purpose of the system. `docs/SCOPE.md` under v0.3 records why that point of
view changed; the rules it must obey are hard constraint 7 in `CLAUDE.md`.

![Vayudoot architecture](architecture.svg)

## The detection layer

### Signals — `schemas.py`

Everything the detection layer consumes is a `Signal`: one observation that something is
polluting at a place and a time. A citizen's classified photograph is one, a VIIRS thermal
detection is one, a station reading above its standard is one, and a reading from a
low-cost sensor somebody owns is one. Reducing four very different things to a single shape
is what lets a hotspot exist in a district nobody has reported from.

A signal carries two numbers that are routinely far apart and must never be confused.
`strength` is how much the observation is believed; `magnitude` is how bad what it observed
is. A single clear photograph of a small fire is high strength and low magnitude, and a
month of marginal station exceedances is the reverse. Confidence is built from the first
and severity from the second. An earlier version read `strength` for both, which made every
confident report `severe` regardless of what it showed.

`SignalSource` splits on one line, and it is not a line about technology:

| Source | Independent? | Where it comes from |
| --- | --- | --- |
| `satellite` | yes | NASA FIRMS VIIRS, fetched by the scan |
| `ground_station` | yes | OpenAQ v3, fetched by the scan |
| `citizen_report` | no | a case that reached the evidence stage |
| `citizen_sensor` | no | `POST /sensors/readings`, a reading from somebody's own device |

The question the split answers is whether two observations could have been staged by the
same person. Both citizen sources can be coordinated; the two instruments cannot be. A
low-cost sensor is genuine evidence and weaker evidence — it may be indoors, beside a
kitchen, or reporting whatever its owner wants — so it enters at a reliability of 0.5 and
is deliberately outside `INDEPENDENT_SOURCES`. A sensor is as easy to place and misreport
as an account is to create, and letting one corroborate a report would reopen the hole hard
constraint 7 closes.

### Scanning — `scan.py`

Hotspot detection could always raise a hotspot from satellite or station evidence. Nothing
was going and fetching that evidence, so in practice the map only ever showed what somebody
had photographed, which is the failure mode the v0.3 reframe exists to end. This module is
the missing half: it calls the same FIRMS and OpenAQ tools the corroboration graph uses,
converts the payloads with the builders already in `hotspots.py`, and writes the result to
the store.

**Scan targets are places this instance already knows somebody cares about.** Two sources:
the coordinates of every stored case, and the waypoints of every configured corridor. Cases
of every status are included, withdrawn and rejected ones too, because a scan point is an
area to point public instruments at rather than a claim about a report — dropping one would
only make the map blind at a coordinate somebody once thought worth flagging. Corridors are
what give the scan reach beyond where citizens have reported, which is most of the country.
Points closer together than half the scan radius are thinned out, since two points that
close cover largely the same square of sky and the same nearest station, and spending two
external requests to learn one thing is the cost that limits how often the scan can run at
all.

**Nothing here starts a loop.** Importing the module has no effect; something has to call
`run_once`, and `run_once` checks `vayudoot_scan_enabled` before doing anything. The flag
is off by default because an unattended process calling two external APIs on a timer should
be switched on by whoever is watching the quota, not by an import. The timer itself lives
in the FastAPI lifespan and starts only when the flag is set. Note what this is *not*:
`SCOPE.md` keeps automatic escalation out of scope because an unsupervised process acting
on a legal deadline is a different class of risk. Scanning has no such property. It fetches
public observations and writes them to a store; nothing is filed and nothing is sent.

**No model is involved.** The whole scan is two HTTP calls per point and some arithmetic.
This is the one part of the system that runs unattended and repeatedly, and hard constraint
5 says inference is the only running cost, so the repeating part is the last place to spend
it. Reading a photograph needs judgement; fetching a CSV of thermal anomalies does not.

**A failed source degrades the scan, it does not fail it.** Tools return `{"error": ...}`
rather than raising, and a pass that gave up because OpenAQ was briefly down would throw
away the satellite detections it already had. `run_once` returns its errors as a list of
sentences rather than a count, because a scan that quietly returned zero signals through an
expired key looks exactly like a scan of clean air, and those are the two states that most
need telling apart.

Signals are deduplicated on `signal_id` on the way into the store, and the id identifies
the *observation* rather than the fetch: a VIIRS detection by its coordinates and
acquisition time, a station reading by its station and parameter. That makes deduplication
a correctness property rather than tidiness. Severity rises with how persistent a hotspot
looks and confidence with how many sources agree, so a scan that ran twice over overlapping
ground would otherwise talk the system into a more serious hotspot than the evidence
supports.

### Hotspots — `hotspots.py`

Detection is derived on demand from stored signals rather than stored itself, for the same
reason clusters are: membership changes whenever a signal arrives, and a cached answer
would be wrong within the hour. `current()` reads both halves of the evidence — signals
built from the cases citizens submitted, and signals the scan fetched — deduplicates the
join, and groups what is left.

**Grouping.** Classified signals group only with their own pollution type, exactly as
clusters do: a waste fire and a construction site at identical coordinates are two problems
under two statutes. Satellite and station signals are *unclassified* by construction —
VIIRS sees heat, not fuel, and calling a thermal anomaly crop residue burning because it
sits over farmland would be the system inventing the one fact a complaint turns on. Those
signals are offered to whichever classified group they overlap, and only form groups of
their own if none does. That is the mechanism by which a citizen photograph upgrades a
satellite detection rather than sitting beside it as a second dot.

**One signal is enough to publish.** `vayudoot_hotspot_min_signals` is 1, and it is the
sharpest difference from clustering, which needs three. A single VIIRS detection is an
instrument in orbit recording a fire; requiring it to repeat would discard exactly the
hyper-local event the brief says macro monitoring misses. Confidence, not suppression, is
how a thin hotspot is reported honestly.

**Confidence is capped, not penalised, when nothing independent agrees.** It starts at the
strongest signal's strength and is lifted by agreement between *distinct sources* rather
than by volume — 0.15 per extra source, to a maximum of 0.3. Ten photographs of one fire
are one fire seen ten times; a photograph plus a satellite detection plus a station
exceedance is three instruments that cannot all be wrong the same way. A hotspot with no
independent source is then held at `vayudoot_hotspot_uncorroborated_cap`, which is 0.6. A
cap rather than a penalty because quantity is precisely what a coordinated campaign can
manufacture, and 0.6 because it sits below the 0.7 the severity bands treat as high: an
uncorroborated hotspot is always visible, always marked, and never top of the list. This is
the line hard constraint 7 draws.

**Radius has a floor, and the floor is not cosmetic.** A hotspot's radius is how far its
signals actually spread from the centroid, floored at `vayudoot_hotspot_min_radius_km`,
which is 1 km. A hotspot drawn tightly around one building is a public accusation against
whoever occupies it, whether or not a name appears anywhere on the page. A kilometre is a
neighbourhood: enough to dispatch an inspector to, not enough to point at a gate.

**Severity reads magnitude and adds persistence**, `min(signals / 10, 0.2)`, and rounds
before banding. That rounding is load-bearing rather than tidy: 0.7 + 0.2 is
0.8999999999999999 in binary floating point, so an unrounded comparison drops a hotspot a
whole band on a representation artefact.

**Thresholds are the Indian standards.** A station reading becomes a signal only if it
exceeds the NAAQS 24-hour standard for its pollutant, and a reading below its standard
produces no signal at all — a station reporting clean air is evidence of nothing happening
and must not put a dot on a map. That is not the same as the reading being useless: the
corroboration stage reads a normal value too, because there it argues *against* a citizen's
report, which is a different job. The reading is converted to µg/m³ before comparison
rather than trusted to arrive in the table's unit. The standards table once held CO's
2 mg/m³ verbatim while OpenAQ reported CO in µg/m³, and a real Ludhiana reading of
1680 µg/m³ — comfortably below the standard — scored as a maximum-severity exceedance. A
thousand-fold unit error is invisible in a number and glaring on a map. An unrecognised
unit costs one signal rather than being guessed at.

These are the Indian standards and not the WHO guidelines, which are several times
stricter. A hotspot is raised so that an Indian authority acts on it, and it must be
measured against the number that authority is bound by; a map flagging half the country for
exceeding a guideline nobody is obliged to meet tells an inspector nothing.

### Grouping — `grouping.py`

Centroid linkage in space and time, generic over what is being grouped. It was extracted
from `clustering.py`, which grouped citizen cases and was the only caller until hotspot
detection needed the same rule for satellite detections and station readings.

The extraction is the decision worth recording. Two copies of this would have drifted, and
the drift would have been invisible: both would still produce groups, just not the same
ones, and the map would quietly disagree with the complaint drafted from it.

The rule is `clustering.py`'s and the reasoning is unchanged. Proximity is measured to the
group's **centroid**, never to its nearest member, because member linkage chains — a line
of observations 400 m apart would walk across a city and report one absurd group — while
centroid linkage bounds a group's diameter to roughly twice the radius, which is the
behaviour a complaint can defend. The window is a maximum **gap** rather than a maximum
age, so a site that burns every fortnight for six months is one ongoing pattern. Items are
consumed in timestamp order, which is what makes the output deterministic, which is in turn
what lets a group's identity be stable enough to cite.

The two callers set different numbers on purpose. Clustering uses 500 m and 30 days:
500 m holds together two sightings of one waste fire photographed from either end of a
lane, and 30 days is the statutory response window, so a pattern inside it happened while
the authority had the case. Detection uses 2 km and 14 days: 2 km absorbs the error of a
375 m VIIRS pixel located to the pixel rather than to the fire inside it, and a fortnight
answers whether something is happening *now* rather than whether an authority sat on
something.

## Forecasting — `agents/forecast.py`, `corridors.py`

The brief asks for forecasts and nothing in the system predicted anything. Vertex AI is the
obvious tool for it and the free-tier constraint rules it out, so what this does instead is
reason over public data with the model already in use.

That makes the honesty of the label the whole design. **This is not a trained predictor.**
It is Gemini reading an Open-Meteo pollutant forecast, an Open-Meteo wind forecast and the
hotspots this instance has detected, and saying what it thinks follows.
`AirQualityForecast` carries `basis` so a reader can check the work and `disclaimer` so
nobody mistakes it for an advisory, and hard constraint 7 requires both to survive every
rendering. It must never present itself as, or be confusable with, a CPCB or IMD forecast.

The stage runs on the `fast` tier like every other tool-calling stage. It reads three
payloads of numbers and writes a short structured judgement, which is the work flash-lite is
for; the two primary-tier stages stay the two that read a photograph and draft a legal
document.

**Which hotspots are offered to the model is geometry; whether the wind is bringing one is
the model's judgement.** `upwind_hotspots` selects on distance alone, within
`vayudoot_forecast_upwind_km`, and hands the model each one's bearing, distance, severity,
confidence and corroboration state. Deciding upwind-ness here would be geometry pretending
to be meteorology. The reach is 400 km, set against the 72-hour horizon rather than a single
night: at the 3-5 m/s typical of the Indo-Gangetic plain in burning season air covers
260-430 km a day. The number is checked against the case the whole thing exists for.
Ludhiana to Delhi is 286 km, and the first guess of 200 km would have put Punjab's burning
outside Delhi's forecast entirely.

**A peak window that has already passed is dropped.** Observed on a live run: asked for a
72-hour outlook, the model returned a peak window beginning the previous day. It was reading
a forecast series that starts at midnight and reporting the whole of it, which is reasonable
as arithmetic and wrong as a forecast — a reader shown "peak: yesterday" concludes the
system is broken, and they are not wrong to. A wholly past window is removed rather than
moved, because inventing a replacement would be exactly the guess the prompt forbids; a
window that merely starts in the past is clipped to now, since the part still ahead is a
real prediction.

**Corridors are data.** `data/corridors.json` holds each corridor's name, states, and four
to eight sparse waypoints along its real alignment, and adding one is a JSON edit — the
authority table's rule, applied again. Nothing in `corridors.py` names a state, a city or a
route. Each waypoint in the data file also carries the name of the place it sits on, which
`Corridor` does not keep: nothing downstream needs the label, but forty bare coordinate
pairs are unreviewable, and a name is what lets somebody check a number against a map before
trusting a forecast built on it.

`corridors_near` measures distance to a corridor's **line**, not to its nearest waypoint.
The waypoints are sparse by design, so nearest-waypoint distance would put a town midway
between Vadodara and Surat sixty kilometres from a corridor that runs straight through it,
and that corridor's forecast would never be offered to the place that needs it most.

A corridor forecast runs every waypoint in parallel — they share no state and each is one
fast call — and takes the **worst** risk any of them carries rather than an average. A
corridor is a population strip and a supply line, so the segment in trouble is what an
authority needs to see, and averaging it away would hide exactly the thing worth acting on.
A waypoint whose call failed is dropped rather than allowed to sink the corridor, and the
summary reports how many of the waypoints answered.

## Federation — `federation.py`

The brief asks for a platform designed so that Indian cities and states can share
predictive models and coordinate resources. **What this shares is a detection layer, not
trained weights.** A node publishes the hotspots it has found on a versioned open feed and
reads its neighbours'. Federated training across state instances is a real idea and is not
what this is; claiming it without building it would cost more than it earns.

`docs/federation.md` is the contract — the feed shape, the versioning, and the argument in
full. Three properties belong here because they are decisions about how the code behaves:

**The published projection is an allowlist.** `FeedHotspot` is written out field by field
rather than being a serialised `Hotspot`, for `register.py`'s reason: a field added to
`Hotspot` later stays private until somebody publishes it on purpose. Signals and case ids
are not in it. A neighbour needs to know that something is burning and how sure we are; it
has no business knowing which of our citizens reported it.

**Uncorroborated hotspots are published too**, carrying their flag and their capped
confidence. Withholding them would be the wrong call twice over: a neighbour deciding what
to trust needs to see the weak signals as well as the strong ones, and hiding them would
mean a citizen-reported fire nobody has corroborated yet is invisible to the state downwind
of it, which is precisely the gap the network exists to close.

**A neighbour's hotspots never become our own.** They are carried with their origin node
attached and used as forecasting context only. They are not stored, not detected against,
and not republished. A node that laundered a neighbour's detection into its own feed would
let one bad instance contaminate the whole network, and corroboration would be meaningless
because nobody could tell whose evidence a hotspot rested on. `fetch_neighbour` also
refuses a feed reporting our own node id, which is what a load balancer, a copied
configuration or a mirroring peer produces: reading our own hotspots back would double every
one of them and look like independent agreement.

Like every tool in the project, `fetch_neighbour` returns a dict and never raises. A peer
that is down, slow or serving something unparseable is an ordinary condition on a federated
network, and a node whose forecasting stops because a peer is offline is worse than one that
carries on with less context.

## The reporting pipeline — one action available from a detection

Everything below is the v0.2 system, still running and still accurate. What changed is its
position: a hotspot is the thing being acted on, and drafting a complaint about it is one of
the available actions rather than the point of the exercise. A case still produces a
`citizen_report` signal when it clears the evidence stage, so the pipeline also feeds the
detection layer.

### Why this shape

The work being automated is a sequence with one genuine fan-out in the middle.
Classification must happen before corroboration, because you cannot corroborate a report
until you know what is being claimed. Jurisdiction must be resolved before drafting, because
the statute cited depends on the authority. Those are real dependencies, so those stages are
a pipeline.

Corroboration is different. Satellite thermal detections, ground station readings, and
meteorological conditions are independent of one another, and none needs the others' output.
That is a real fan-out, so it is a Strands agent graph with three entry points converging on
a synthesis node. Using a graph for the whole system would have been decoration; using one
here is the shape of the problem.

### 0. Intake — `images.py`

Not an agent, and it runs before the pipeline does. Model content blocks accept four image
formats; phones do not restrict themselves to four. iOS produces HEIC by default, and people
upload TIFF, BMP, and screenshots in whatever the tool emitted.

The format is decided by decoding the bytes, never by the file extension. That also means
the supported set is "whatever Pillow reads" — roughly seventy formats, AVIF and HEIC
included — rather than a list kept here. A list would need amending every time a phone
vendor changed its default, which is how the bug below happened in the first place. That
distinction was a real bug rather than a hypothetical one: an unrecognised suffix used to be
rewritten to `.jpg`, so HEIC bytes reached the model labelled as JPEG and it saw nothing,
silently, with the case proceeding as though a photograph had been read.

Normalising also does two things the classification depends on. It applies EXIF rotation to
the pixels, because a model reads pixels and not the orientation tag, so a portrait phone
photograph would otherwise arrive on its side. And it caps the longest edge at 1568 pixels:
a 12 megapixel photograph carries far more detail than a classification uses, and every
pixel above that is tokens spent for nothing, which matters when inference is the only
running cost. An image that is already acceptable, upright and small enough passes through
byte for byte rather than being re-encoded.

Unreadable bytes are a `415` at the API boundary. Failing at the door gives the citizen
something to act on; failing at the model gives them a case that dies four seconds later for
no visible reason.

### 1. Evidence — `agents/evidence.py`

A single agent with no tools, on the `primary` tier. Up to four photographs are passed as
Strands image content blocks in one message and the agent returns an `EvidencePacket`
through structured output. Four is a budget line, not a design limit: each image is roughly
1,500 tokens at the 1568-pixel edge intake normalises to, and inference is the only running
cost here.

The prompt pushes toward conservatism, and the pipeline enforces a confidence floor of 0.55.
Below it, the case halts with status `rejected` and a note asking for human review. This
matters because the output of this stage becomes a formal complaint against a real party,
and because it is the number that becomes a signal's `strength` on a public map.

**A report with no photograph is still a report**, and for a while it was silently broken.
The API accepts one — a citizen who cannot photograph safely, a night fire, a moving vehicle
— but the prompt was written entirely around an image, so the model correctly answered
`unclear` and every such case halted at the floor. The evaluation harness found it on its
first live run. The prompt now handles a written account that names observable things, with
an explicit confidence band that keeps a note below the ceiling a photograph earns: real
evidence, weaker evidence, and the number says so.

### 2. Corroboration — `agents/corroboration.py`

A `GraphBuilder` graph, three parallel entry points into one synthesis node. Every node is
on the `fast` tier, synthesis included: each one calls a tool and summarises, which is what
the cheap tier is for.

| Node | Tool | Source |
| --- | --- | --- |
| `satellite` | `find_satellite_fire_detections` | NASA FIRMS VIIRS |
| `ground_station` | `get_nearby_air_quality` | OpenAQ v3 |
| `meteorology` | `get_wind_conditions` | Open-Meteo |
| `synthesis` | none | joins the three, returns `Corroboration` |

The meteorology tool also back-traces the plume. Meteorological wind direction is the
bearing the wind blows *from*, so anything carried to the report location originated along
that same bearing; the tool projects two kilometres along it and returns a candidate source
coordinate.

The synthesis prompt is explicit that absent evidence is not disproof. Hyper-local events
routinely fall below satellite resolution and happen far from the nearest monitoring
station — which is the exact gap this project exists to close, so treating silence as a
negative would defeat the purpose.

Note that this stage and the detection layer read the same two sources for different
questions. Corroboration asks whether independent evidence supports *this report*; detection
asks what the instruments are seeing *anywhere*, whether or not anyone reported it.

### 3. Jurisdiction — `agents/jurisdiction.py`

An agent on the `fast` tier with two tools: reverse geocoding, then a lookup against a
data-driven authority table keyed by administrative region and pollution category.

The table is JSON, not code. Pointing the system at another state or another country is a
data change. The prompt forbids inventing an authority, an address, or a statute section.

**Coverage is reported, not assumed.** A fixed table has edges, and the failure at those
edges used to be silent: if a category called for a municipal body and the city was not
listed, the lookup quietly returned the state board and relabelled the tier, so a
substitution was indistinguishable from a match. The tool now returns `coverage` — `exact`,
`fallback`, or `generic` — with a note explaining it, the agent copies both into the
`Jurisdiction`, and the case shows a warning for anything other than `exact`.

Asking the agent to report its own accuracy is only worth so much, so the pipeline checks
the one thing that can be checked deterministically: an address that exists only in the
generic fallback entry means the region was absent, whatever the model said.
`GET /authorities` publishes the whole table, and the interface has a Coverage tab, so the
limit is visible before a citizen submits rather than after.

### 4. Drafting — `agents/drafting.py`

A single agent on the `primary` tier, structured output to `Complaint`. It receives the
evidence, the corroboration, and the jurisdiction, and is instructed to cite only the
statute supplied to it. It produces an English body and a translation into the region's main
language.

The prompt forbids exaggeration, naming an accused party, and claiming certainty beyond the
evidence — all three of which get complaints dismissed.

### 5. Filing, escalation and the lifecycle — `filing.py`, `lifecycle.py`

Filing writes an envelope to a local sandbox outbox. Live filing raises rather than sends.

The two modules are split along a real line. `filing.py` produces envelopes and is governed
by the live-filing rule; `lifecycle.py` records what came back and sends nothing.
Acknowledge, resolve and withdraw live in the second.

**The escalation clock is the design decision here.** An acknowledgement could stop it, be
ignored, or restart it. Stopping it is wrong in the specific way this project exists to
counter: an acknowledgement is a receipt, not a remedy, so one automated "your complaint has
been received" would silence the tracker forever. Ignoring it is unfair the other way — an
authority that genuinely replies on day 29 would be escalated the next morning. So it
restarts. `escalation_due()` reads the window's start from a map of status to field: `FILED`
counts from `filed_at`, `ACKNOWLEDGED` from `acknowledged_at`, anything else is never due.
`ESCALATED` is deliberately absent, because a case escalates once — the authority table has
no third tier.

`TERMINAL_STATUSES` is the single definition of finished: resolved, withdrawn, rejected,
failed. A withdrawn case cannot then be filed or escalated. Three of those four also stop a
case contributing a signal to the map: `rejected` fell below the evidence floor so the
photograph never supported anything, `withdrawn` was taken back and must not go on holding a
place on a public map, and `failed` may carry no evidence at all. `resolved` and
`acknowledged` stay in, because a problem that was fixed and came back is the strongest
pattern there is.

### 5b. Clustering — `clustering.py`

Pure arithmetic over `store.all_cases()`, recomputed on every request rather than stored,
because membership changes as reports arrive and a cached answer would be wrong within the
hour. It uses `grouping.link` — the same centroid linkage hotspot detection uses, with
tighter numbers.

A cluster and a hotspot are not the same object and the difference is worth stating plainly.
A cluster is repeat *citizen cases* at one place, used inside a complaint to argue that an
authority sat on a pattern. A hotspot is what the map shows, and it can exist with no
citizen involvement whatsoever.

Pollution type must match exactly and `unclear` never groups — a waste fire and a
construction site at identical coordinates are two problems under two statutes.

Reporter independence is only partly knowable, so it is published rather than guessed:
distinct contacts and anonymous submissions travel with the cluster as separate numbers, and
both the drafting prompt and the interface are forbidden from reading them as independent
witnesses.

### 5c. RTI — `agents/rti.py`

When the window lapses, the real lever is a Right to Information application to the
authority's Public Information Officer, carrying a statutory thirty-day duty to reply that
the complaint never had.

It is a **separate citizen action, not a step inside escalation**. Escalation re-files the
same complaint one tier up; an RTI asks the original authority what is on the file.
Different addressee, different statute — and an application made in a person's own name with
their own fee cannot be an automatic consequence of a timer. Its clock runs from `filed_at`
and nothing restarts it: an acknowledgement earns a fresh escalation window because it
promises action, but a receipt is not an answer to "what is on the file".

The prompt spends most of its length on the distinction that gets applications rejected —
information *held on a file*, never a demand for action or an opinion. The statutory
scaffolding is rendered deterministically rather than model-written, no PIO name is
invented, and every field a human must supply is a bracketed placeholder listed in the
document.

### 5d. Evidence pack and public register — `pack.py`, `register.py`

The pack is one self-contained HTML file. Indic scripts need real shaping — reordered
matras, conjuncts — and several pure-Python PDF writers drop what they cannot shape without
erroring, while a browser already has the shaping engine and prints to PDF anyway.
Photographs are `data:` URIs, styles are inline, and the map is a locator SVG generated from
the case's own coordinates, because a tile service needs a key and would render as a broken
image offline.

The register is an **allowlist**, not a denylist, so a field added to `Case` later is private
by default. See "Who can see what" in the README for the visibility rule and why a
non-public case answers 404 rather than 403.

## Interface and HTTP surface — `api.py`, `web/`

**The operations view is the landing surface.** The empty hash routes to `ops`, not to the
report form. That swap is the v0.3 reframe in one change: through v0.2 the protagonist was a
citizen with a grievance, and here it is the city or state air-quality cell that has to
decide what to look at this morning. Nav is **Live / Report / Cases / Coverage**, in that
order and for that reason. Intake did not go anywhere; it is one route along and no further
from a thumb than it was.

`OpsView.js` puts the map first and large, because the question is "where", with the ranked
list beside it because the question after that is "which one first". The two are the same
data twice: the map is not an illustration of the list and the list is not a caption for the
map, which is also what makes the view usable without a mouse or without sight — everything
the circles say is in the rows. `HotspotsMap.js` and `HotspotMarks.js` draw hotspots as
areas at their published radius, never as points. `HotspotCard.js` and `HotspotView.js`
always show confidence next to the corroboration flag, because an interface that shows the
confidence without the flag is hiding the part that matters.

The empty state is designed rather than defaulted. It is the state an unconfigured instance
is in most of the time and the one a first-time reader is most likely to hit, and the one
sentence it must get right is that an empty map is not clean air.

Views mount only while they are the route, which is what stops the case poll and the hotspot
poll when the reader leaves. The report form is the one exception, and only after its first
visit: once opened it stays in the document so a half-filled form survives a look at the
map. It is not mounted before that, because `LocationPicker` asks for the reader's location
on mount, and the front door of a public dashboard is not the place to raise a geolocation
prompt nobody asked for.

The interface is static files served by the same process — a Preact app in native ES
modules, with the runtime vendored under `web/vendor/` so there is no build step and no CDN
in the request path. One deployment, one URL, no CORS. It is mounted last so it cannot
shadow an API route.

The HTTP surface divides the same way the system does:

| Routes | Layer |
| --- | --- |
| `GET /hotspots`, `GET /hotspots/{id}` | detection, derived on every call |
| `POST /sensors/readings` | detection, a citizen sensor reading in |
| `GET /forecast`, `GET /corridors`, `GET /corridors/{id}/forecast` | forecasting |
| `GET /node`, `GET /feed`, `GET /neighbours` | federation |
| `POST /reports`, `GET /cases/…`, `POST /cases/{id}/…` | the reporting pipeline |
| `GET /clusters`, `GET /authorities`, `GET /register` | supporting the above |

Both forecast routes read this node's hotspots and its neighbours' together, which is the
whole point of federating: Punjab's burning is the best available explanation of a Delhi
morning, and a node that can only see its own reports learns about it when the smoke
arrives.

**A run is minutes of model calls, which no browser will wait through on a form
submission.** So `POST /reports` writes the case to disk, starts the pipeline as a
background task, and answers `202` with a case id. The page then polls `GET /cases/{id}` and
renders whatever has landed.

That is why a case carries two fields rather than one. `status` is the case's legal
lifecycle — `awaiting_confirmation`, `filed`, `acknowledged`, `escalated`, `resolved`,
`withdrawn`, `rejected`, `failed`. `stage` is how far the machinery has got — `received`,
`evidence`, `corroboration`, `jurisdiction`, `drafting`, `complete`, `halted`. A case is
`draft` for the whole run; without `stage` there would be nothing to show during it.

The pipeline saves after every stage for the same reason: partial state has to be readable
from disk the moment it exists, not at the end. A stage that raises is caught, and the case
is left as `failed` with the exception recorded on it and `stage` parked on whatever was
running when it died — a run that dies must leave a readable case rather than a 500 and no
trace.

Two endpoints exist purely for the interface: `/cases/{id}/photo`, which serves the
submitted photograph and refuses any path that does not resolve inside the uploads
directory, and `/cases/{id}/envelope`, which returns the filed envelope exactly as it was
written to the sandbox outbox — the point of the demo is that you can read what would have
been sent.

`POST /reports` is the one endpoint that costs money. It is rate limited on a rolling
per-client window and a global daily cap, both in process, because a report is about ten
model calls against a metered free tier and the URL is public. The client key is the first
`X-Forwarded-For` hop, which is forgeable — which is exactly why the global cap sits
underneath it rather than trusting it. The upload is capped before the multipart parser
spools it and counted as it is read, since a `Content-Length` header is a claim rather than
a fact. `POST /sensors/readings` shares that limiter even though it spends no model quota,
because an open write to the signal store is an open write to the map.

## State

`Case` is the single object that accumulates across the reporting pipeline, holding the
report, every intermediate result, a status, a stage, any error, and an append-only history.
It is persisted as JSON by `store.py` because a case outlives the request that created it: a
complaint filed today is chased for weeks. Setting `DATABASE_URL` moves the same store to
Postgres; nothing else changes, which is the property the module was written for.

`Signal` is the detection layer's stored object and the second thing `store.py` keeps. It is
stored rather than derived because an observation is a fact about a moment that has passed,
and `save_signals` leaves an id already held exactly as it was: re-reading an observation
later cannot tell us anything new about it. `Hotspot` is the opposite and is deliberately
*not* stored — it is recomputed from the live signals on every request, because membership
changes whenever a signal arrives. `live_signals()` applies the retention window;
`all_signals()` still has everything, because the record of what was observed is worth
keeping even once it stops being current.

## Evaluating the prompts — `evals/`, `scripts/eval.py`

The test suite replaces the agent stages with fakes, which is what makes the pipeline
testable offline — and it means the seam between this code and a model is untested by
construction. Corroboration has been wrong twice in ways no test could see: once discarding
its own structured output, once reporting `corroborated` from a wind bearing alone.

The harness closes that gap. Fixtures are data, so adding a case is an edit to a manifest.
Corroboration cases replay recorded FIRMS, OpenAQ and Open-Meteo outputs, which makes
exactly the regression that shipped deterministic and free — they run offline with no
provider and no network. Classification and refusal need a model and are skipped unless
asked for.

It scores calibration, not just accuracy: a classifier answering 0.95 to everything is
useless at 90% accuracy, and the 0.55 floor is meaningless if nothing ever falls below it.
Live runs print their projected call count before spending anything, and comparing two runs
is a first-class operation, because comparing a prompt before and after an edit is the
entire point.

## Provider abstraction

`models.build_model()` is the only place a provider is constructed, and
`settings.provider_for(tier)` is the only thing that decides which one.

**The shipped configuration puts both tiers on Gemini** — primary on flash, fast on
flash-lite. That is hard constraint 6 and it is a rule rather than a preference: the target
hackathon does not consider a submission without Google AI integration, and shipping the two
judgement calls on Ollama would put the only inference a judge would call meaningful on a
non-Google model.

The abstraction survives that narrowing for two reasons. Ollama remains a supported provider
for local development and the offline test suite. And a system a state could run on its own
hardware is part of the deployability argument, so being able to move the whole thing with
one environment variable earns its keep even while nobody is using it in production.

The tier split also survives, as a cost control inside one provider. Two agents are on
`primary`: evidence, which reads a photograph, and drafting, which writes a legal complaint.
Everything else — the three corroboration nodes, the synthesis node, jurisdiction, and the
forecast stage — is on `fast`, because each of them calls a tool and summarises what came
back. The scan spends no inference at all.

## Deliberate omissions in the prototype

- No delivery transport. This is a safety property, not a gap.
- JSON file storage by default, with Postgres behind one environment variable.
- The authority table covers **every one of India's 28 states and 8 union territories** —
  36 regions, each with its pollution control board or committee, its largest municipal
  bodies, and the Central Pollution Control Board as the escalation body — plus a generic
  fallback for anything a geocoder names in a way the table does not hold. The file has 40
  keys because four are aliases for regions a geocoder may still name the old way (Orissa,
  Pondicherry, and Dadra and Nagar Haveli and Daman and Diu named separately). Adding a
  region is a JSON edit.
- No authentication on the API. This is why the privacy boundary is drawn at each surface
  instead: the reporter's contact is excluded from every route that returns a `Case`, the
  register republishes through an allowlist, and the federation feed publishes through a
  second one.
- No scheduler for escalation or RTI drafting. Both are reachable and both are manual,
  because an unsupervised process acting on a legal deadline is a different class of risk
  from a bug. The signal scan *is* on a timer, and the distinction is deliberate: it fetches
  public observations and writes them to a store, files nothing, and is off by default
  anyway.
- No trained forecasting model, and no federated training. Both are stated as such wherever
  they could be mistaken for otherwise.

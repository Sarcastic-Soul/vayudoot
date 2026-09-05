# Architecture

## Why this shape

The work being automated is a sequence with one genuine fan-out in the middle.
Classification must happen before corroboration, because you cannot corroborate a
report until you know what is being claimed. Jurisdiction must be resolved before
drafting, because the statute cited depends on the authority. Those are real
dependencies, so those stages are a pipeline.

Corroboration is different. Satellite thermal detections, ground station readings,
and meteorological conditions are independent of one another, and none needs the
others' output. That is a real fan-out, so it is a Strands agent graph with three
entry points converging on a synthesis node. Using a graph for the whole system
would have been decoration; using one here is the shape of the problem.

## Stages

### 1. Evidence — `agents/evidence.py`

A single agent with no tools. The photograph is passed as a Strands image content
block and the agent returns an `EvidencePacket` through structured output.

The prompt pushes toward conservatism, and the pipeline enforces a confidence
floor of 0.55. Below it, the case halts with status `rejected` and a note asking
for human review. This matters because the output of this stage becomes a formal
complaint against a real party.

### 2. Corroboration — `agents/corroboration.py`

A `GraphBuilder` graph, three parallel entry points into one synthesis node.

| Node | Tool | Source |
| --- | --- | --- |
| `satellite` | `find_satellite_fire_detections` | NASA FIRMS VIIRS |
| `ground_station` | `get_nearby_air_quality` | OpenAQ v3 |
| `meteorology` | `get_wind_conditions` | Open-Meteo |
| `synthesis` | none | joins the three, returns `Corroboration` |

The meteorology tool also back-traces the plume. Meteorological wind direction is
the bearing the wind blows *from*, so anything carried to the report location
originated along that same bearing; the tool projects two kilometres along it and
returns a candidate source coordinate.

The synthesis prompt is explicit that absent evidence is not disproof. Hyper-local
events routinely fall below satellite resolution and happen far from the nearest
monitoring station — which is the exact gap this project exists to close, so
treating silence as a negative would defeat the purpose.

### 3. Jurisdiction — `agents/jurisdiction.py`

An agent with two tools: reverse geocoding, then a lookup against a data-driven
authority table keyed by administrative region and pollution category.

The table is JSON, not code. Pointing the system at another state or another
country is a data change. The prompt forbids inventing an authority, an address,
or a statute section, and requires the agent to say when it matched only a
generic default.

### 4. Drafting — `agents/drafting.py`

A single agent, structured output to `Complaint`. It receives the evidence, the
corroboration, and the jurisdiction, and is instructed to cite only the statute
supplied to it. It produces an English body and a translation into the region's
main language.

The prompt forbids exaggeration, naming an accused party, and claiming certainty
beyond the evidence — all three of which get complaints dismissed.

### 5. Filing and escalation — `filing.py`

Filing writes an envelope to a local sandbox outbox. Live filing raises rather
than sends. Escalation compares the filing timestamp against the statutory
response window carried on the `Jurisdiction` object and re-files to the
escalation authority when it lapses.

## State

`Case` is the single object that accumulates across stages, holding the report,
every intermediate result, a status, and an append-only history. It is persisted
as JSON by `store.py` because a case outlives the request that created it: a
complaint filed today is chased for weeks. Replacing `store.py` with Postgres
touches no other module.

## Provider abstraction

`models.build_model()` is the only place a provider is constructed. This exists so
that the same agent code runs on Bedrock or Gemini unchanged, which is the point
of the Strands provider abstraction and also what keeps the Google-hosted
deployment path open without a rewrite.

## Deliberate omissions in the prototype

- No delivery transport. This is a safety property, not a gap.
- JSON file storage rather than a database.
- The authority table covers two states plus a generic fallback.
- No authentication on the API.

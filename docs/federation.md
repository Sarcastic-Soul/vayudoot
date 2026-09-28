# Federation

**What is shared is a detection layer, not trained weights.**

That sentence is the honest reading of the brief's "share predictive models and
coordinate resources", and it is worth stating first because the dishonest
reading is so available. Federated training across state instances is a real
idea. It is not what this does, it could not have been built in the time
available, and claiming it in a deck without building it would cost more than it
earns.

What a node actually shares is the thing a neighbour can use immediately: the
hotspots it has detected, on an open versioned feed, with the confidence and the
corroboration state attached.

## Why it is worth having

Stubble burning in Punjab and Haryana arrives in Delhi about a day and a half
later. This is the single best-documented pollution event in India and it crosses
a state boundary, which is exactly why no single-state system catches it.

A Delhi instance that can only see Delhi's own reports finds out when the smoke
does. A Delhi instance reading a Punjab node's feed can forecast it while the air
is still clean.

That is the whole argument, and note what it does *not* require: no shared model,
no shared training data, no central authority, no agreement beyond a URL and a
JSON schema. A node publishes what it found. A neighbour reads it. The
forecasting stage is handed both.

### The border does not stop it either

The two Punjabs are one paddy belt split by an international border. Pakistan's
Punjab burns the same stubble on the same calendar, Lahore is fifty kilometres
from Amritsar, and the autumn north-westerly that carries Ludhiana's smoke to
Delhi carries Lahore's with it. It is the best-documented trans-boundary smog
event in South Asia, and a network that federates only inside one country sees
half of it.

Nothing in the contract is Indian. A node says which country it is in
(`country`, ISO 3166-1 alpha-2, on `/node` and in every feed), and a Delhi node
reads a feed from Lahore exactly as it reads one from Ludhiana — as forecasting
context under the rules below, never as its own detection. The corridor table
carries the route as data: `lahore-delhi-transboundary` runs Lahore → Amritsar →
Jalandhar → Ludhiana → Ambala → New Delhi.

## The contract

### `GET /node`

Who this instance is.

```json
{
  "node_id": "punjab-node",
  "name": "Punjab State Air Quality Cell",
  "region": "punjab",
  "country": "IN",
  "instance_url": "https://punjab.example.org",
  "contact": "airquality@punjab.example.org"
}
```

`country` was added inside feed version 1.0 because it defaults to `IN`: a feed
from a node running an older build, which does not send it, still validates.

### `GET /feed`

The hotspots this node has detected, as a versioned document.

```json
{
  "feed_version": "1.0",
  "node": { "node_id": "punjab-node", "...": "..." },
  "generated_at": "2026-09-15T04:00:00Z",
  "hotspot_count": 12,
  "hotspots": [
    {
      "hotspot_id": "VDH-1A2B3C4D",
      "node_id": "punjab-node",
      "pollution_type": "crop_residue_burning",
      "centre_latitude": 30.901,
      "centre_longitude": 75.8573,
      "radius_km": 4.2,
      "confidence": 0.93,
      "severity": "severe",
      "corroborated": true,
      "signal_count": 7,
      "first_seen_at": "2026-09-13T22:10:00Z",
      "last_seen_at": "2026-09-15T03:40:00Z"
    }
  ]
}
```

Three properties of that document are deliberate.

**It is an allowlist, not a serialised `Hotspot`.** Signals and case ids are not
in it. A neighbour needs to know that something is burning and how sure we are;
it has no business knowing which of our citizens reported it. A field added to
`Hotspot` later stays private until somebody publishes it on purpose. The same
choice `register.py` makes, for the same reason.

**Uncorroborated hotspots are published, carrying their flag.** Withholding them
would hide a citizen-reported fire from the state downwind of it, which is the
gap this network exists to close. Publishing them unmarked would be worse. So:
published, flagged, and with the capped confidence that comes with being
uncorroborated. A neighbour deciding what to trust needs the weak signals as well
as the strong ones, and the flag is what lets it decide.

**It is versioned.** A second state standing up its own instance is what this is
for, and a feed without a version is a feed nobody can safely change.

**Population exposure is not in it.** Our hotspots carry an `exposure` figure —
how many people live in towns within reach — but it is our gazetteer's
arithmetic over the centre and radius, which are already published. A neighbour
can compute it from its own population data, and a node across a border may
well hold a better table for its own side than we do. Publishing ours would
invite a neighbour to cite our estimate as if it were part of the detection.

### `GET /feed.geojson`

The same feed as an RFC 7946 GeoJSON FeatureCollection. `/feed` is this
project's own contract; GeoJSON is everybody's. QGIS, ArcGIS, Leaflet and Google
Earth open it with no code, which is what lets a pollution control board or
another country's environment agency look at what a node found without adopting
anything of ours first. Served as `application/geo+json`, and withheld with a
404 whenever `/feed` is.

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "id": "VDH-1A2B3C4D",
      "geometry": {
        "type": "Polygon",
        "coordinates": [[[75.8573, 30.938771], [75.848709, 30.938045], "...",
                         [75.8573, 30.938771]]]
      },
      "properties": {
        "hotspot_id": "VDH-1A2B3C4D", "node_id": "punjab-node",
        "pollution_type": "crop_residue_burning",
        "centre_latitude": 30.901, "centre_longitude": 75.8573, "radius_km": 4.2,
        "confidence": 0.93, "severity": "severe", "corroborated": true,
        "signal_count": 7,
        "first_seen_at": "2026-09-13T22:10:00Z", "last_seen_at": "2026-09-15T03:40:00Z",
        "node_country": "IN", "feed_version": "1.0"
      }
    }
  ],
  "feed_version": "1.0",
  "node": { "node_id": "punjab-node", "country": "IN", "...": "..." },
  "generated_at": "2026-09-15T04:00:00Z",
  "hotspot_count": 1
}
```

**Every hotspot is a polygon, never a point.** A point is an address, and a
point on a public map is an accusation against whoever sits under it — hard
constraint 7. The ring is a 32-vertex approximation of the hotspot's circle at
its published radius, placed geodesically, closed and counter-clockwise as the
RFC requires, so the area on the map is exactly the area the feed claims.

**The properties are `/feed`'s allowlist, produced by the same function.**
`publish_geojson()` calls `publish()` and reshapes its output rather than
projecting `Hotspot` a second time, so the two serialisations cannot drift and
the GeoJSON cannot leak a field the feed withholds. The node rides on the
collection as a foreign member (RFC 7946 §6.1), and each feature repeats the node
id and country, because GIS layers are split and merged routinely and a feature
that has lost its collection must still say whose detection it is.

### `GET /neighbours`

What this node's configured peers are currently reporting, and which of them
failed. Read live rather than cached: a peer being unreachable is ordinary on a
federated network, and an operator needs to see which ones answered.

## What a neighbour's hotspots are used for, and what they are not

A neighbour's hotspots are **forecasting context**. They are handed to the
forecast stage alongside our own, so an outlook for Delhi is computed knowing
what Punjab has found.

They are never:

- stored as ours
- detected against, or allowed to merge with our own signals
- republished in our feed

A node that laundered a neighbour's detection into its own feed would let one bad
instance contaminate the whole network, and worse, it would make the
corroboration rule meaningless: nobody downstream could tell whose evidence a
hotspot rested on. Hard constraint 7 in `CLAUDE.md` depends on a hotspot's
provenance being legible, and provenance does not survive being copied.

A feed reporting **our own** node id is refused outright. Through a load
balancer, a copied configuration, or a neighbour that mirrors us, our own
hotspots would come back as somebody else's and double — and two copies of one
detection look exactly like two independent detections.

## Standing up a second node

Everything here is configuration. No code changes, no coordination with anybody,
no registry to join.

### 1. Deploy the instance

Same container, same process as `docs/deployment.md` describes. Free tier
throughout.

### 2. Declare who you are

```bash
VAYUDOOT_NODE_ID=punjab-node              # unique across the network
VAYUDOOT_NODE_NAME="Punjab State Air Quality Cell"
VAYUDOOT_NODE_REGION=punjab               # the region you cover
VAYUDOOT_NODE_COUNTRY=IN                  # ISO 3166-1 alpha-2
VAYUDOOT_NODE_URL=https://punjab.example.org
VAYUDOOT_NODE_CONTACT=airquality@punjab.example.org
VAYUDOOT_PUBLISH_FEED=true
```

`VAYUDOOT_NODE_ID` must be unique. Two nodes sharing one id will refuse each
other's feeds, which is the safe failure but a confusing one to debug.

### 3. Subscribe to your neighbours

```bash
VAYUDOOT_NEIGHBOUR_FEEDS=https://punjab.example.org/feed,https://haryana.example.org/feed
```

Comma-separated. A node with none federates with nobody and works perfectly well
alone — this is additive, and a state that wants to run in isolation loses
nothing it had.

Subscription is one-directional and needs no permission: reading a public feed is
reading a public feed. Two nodes that each list the other are peered.

### 4. Add your own jurisdiction and corridors

Both are data, not code:

- `src/vayudoot/data/authorities.example.json` — your state's boards,
  committees, statutes and escalation paths. The shipped table already covers all
  28 states and 8 union territories at state tier, so this is about adding the
  *municipal* bodies you know and the demo table does not.
- `src/vayudoot/data/corridors.json` — the economic corridors you forecast
  along. Waypoints are sampling points, not a route; four to eight per corridor.
  A node scans and lists only the corridors whose `countries` include its own
  `VAYUDOOT_NODE_COUNTRY`, so one file holds every country's and a cross-border
  corridor is watched from both sides.

**Every committed email address must stay on the `.invalid` TLD.** This is hard
constraint 1 and `tests/test_filing_safety.py` enforces it. Real addresses belong
in a private deployment configuration, never in the repository.

### 5. Turn the scan on if you want one

```bash
VAYUDOOT_SCAN_ENABLED=true
VAYUDOOT_SCAN_INTERVAL_MINUTES=60
```

Off by default on purpose: it is a loop calling two external APIs unattended, and
it should start because somebody watching the quota decided so.

## Standing up a node in another country

The detection layer is already global. FIRMS, OpenAQ and Open-Meteo cover the
planet, the hotspot rules are geometry and arithmetic, and the feed contract has
no field that assumes India. What changes between countries is what a country
*is*: its authorities, its routes, its air quality standards and its towns. All
of those are data or configuration.

**What is data or configuration, and changes:**

- **Node identity.** `VAYUDOOT_NODE_COUNTRY` and the rest of step 2 above. The
  country is what picks the standard, the corridors and the place search below.
- **Authorities.** One table per country, each keyed by administrative region
  with the statute each complaint cites: `authorities.example.json` is India's,
  and `authorities.<cc>.example.json` is any other country's (`za`, `br`). Each
  file names its country in its own `country` field, and **the countries a node
  serves are exactly the countries it has a table for** — nothing in Python lists
  them. A report or a hotspot in a country with no table is refused (a 422 for an
  alert; a rejected case, before any model is called, for a report) rather than
  addressed to another country's placeholder. An uncommitted
  `authorities.<cc>.json` overrides the example for that country, and the
  committed copies keep every address on `.invalid` (hard constraint 1). A table
  also names the country's access-to-information law, and, per region or for the
  whole country, the `local_language` a summary for residents is written in.
- **Response windows.** A table states `response_window_days` only where a
  statute sets one. Where none does — South Africa and Brazil set no deadline for
  answering an air pollution complaint — it is `null` with a note, and the case
  carries the table's `follow_up_days` instead, marked
  `response_window_statutory: false` so nobody reads it as a legal deadline.
- **Corridors.** `src/vayudoot/data/corridors.json`, one file for every country.
  A corridor may cross a border — name a foreign province distinctly in `states`
  and list `countries`. A node scans and lists the corridors that include its own
  country.
- **Exceedance standards.** The thresholds a station reading must pass to become
  a signal are in `src/vayudoot/data/standards.json`, one table per country with
  its notification cited, every value in µg/m³. The node's country picks the
  table; a country without one falls back to the WHO 2021 guidelines, labelled as
  a guideline everywhere it appears. `NAAQS_STANDARDS` still overrides the whole
  table from one environment variable, for a deployment that needs other numbers.
- **Towns for exposure.** `src/vayudoot/data/settlements.csv` is GeoNames
  `cities15000` filtered to India, the neighbours whose smoke reaches it, South
  Africa and Brazil. `scripts/build_settlements.py --countries ...` rebuilds it
  for another air shed.
- **Neighbours.** `VAYUDOOT_NEIGHBOUR_FEEDS`, which may point across a border.

**What stays the same:** the code, the container, the two-tier model setup, the
feed contract and its version, the hotspot rules (minimum radius, corroboration
cap), the human confirmation before anything is filed, and the rule that a
neighbour's hotspots are forecasting context — carried with their origin node,
never stored, detected against or republished as ours. A foreign node is a
neighbour like any other; being foreign earns it neither more trust nor less.

**Two countries that ship.** The repository carries both of these, so starting a
node in either is one environment variable:

- *South Africa.* `VAYUDOOT_NODE_COUNTRY=ZA`. `authorities.za.example.json` names
  the Department of Forestry, Fisheries and the Environment's National Air Quality
  Officer as escalation, the environment department of each of the nine
  provinces, and the metros and districts that are licensing authorities under
  section 36 of the National Environmental Management: Air Quality Act 39 of
  2004 — on the Highveld, Nkangala District for eMalahleni and Middelburg and
  Gert Sibande District for Secunda. Each province carries its most spoken
  household language (Census 2022): siSwati for Mpumalanga, isiZulu for Gauteng
  and KwaZulu-Natal, Afrikaans for the Western Cape. The standard is the National
  Ambient Air Quality Standards (GN 1210 of 2009, GN 486 of 2012 for PM2.5). The
  corridors are Johannesburg to eMalahleni and Middelburg on the N12 and N4, and
  Gauteng to Durban on the N3.
- *Brazil.* `VAYUDOOT_NODE_COUNTRY=BR`. `authorities.br.example.json` names
  IBAMA as escalation and sixteen state agencies, among them SEMAS in Pará,
  SEMA in Mato Grosso, SEDAM in Rondônia, IPAAM in Amazonas, CETESB in São Paulo
  and INEA in Rio de Janeiro, with the municipal secretariats of São Paulo, Rio de
  Janeiro, Manaus and Porto Velho. A clearing fire is cited under Lei
  14.944/2024 and article 41 of Lei 9.605/1998; other pollution under Lei
  6.938/1981, brought as a representation under article 17 of Lei Complementar
  140/2011. Everything is drafted for residents in Brazilian Portuguese. The
  standard is CONAMA Resolution 506 of 2024 at interim stage PI-2, in force since
  January 2025. The corridors are the Via Dutra, BR-163 from Cuiabá to Santarém
  across the arc of deforestation, BR-364 through Rondônia and BR-319 from Porto
  Velho to Manaus.

A node for either would still want its settlements rebuilt with its smoke
neighbours — `--countries BR,BO,PY,AR`, `--countries ZA,MZ,ZW,BW` — and its own
neighbour feeds. Both tables' `_comment` blocks say where each name was checked
and what was left out because it could not be.

**Be exact about what that is.** No South African or Brazilian government body
runs a Vayudoot node, has been approached, or has agreed to anything. The
authority names are real and public, taken from government sources; every
address is a placeholder on `.invalid`. What the tables show is that the system
can be pointed at another country's institutions without a code change, not that
those institutions have been pointed at it.

**What is still not per country.** Honest about the edges:

- The RTI stage drafts under India's Right to Information Act, 2005, and is
  refused (409) for a case in any other country. South Africa's Promotion of
  Access to Information Act and Brazil's Lei de Acesso à Informação are real
  routes, and each table names its law, but a draft for either would be a new
  prompt with that law's own forms, periods and appeals, not a new table row.
- The forecast disclaimer (`FORECAST_DISCLAIMER` in `schemas.py`) disowns "CPCB,
  IMD or any government authority". It is true everywhere but names India's
  agencies as its example.
- The complaint drafting prompt is the same for every country. The statute,
  section, authority, country and local language all come from the table, and the
  prompt is told to cite nothing else, but its sense of complaint practice was
  written with Indian complaints in front of it.

## Trying it locally

`scripts/federation_demo.py` runs the whole thing on one machine: it starts a
second instance as a Punjab node with seeded stubble-burning signals, points a
Delhi node at its feed, and shows the Delhi forecast with and without the
neighbour. Two real processes, the real HTTP contract, no mocking.

```bash
.venv/bin/python scripts/federation_demo.py
.venv/bin/python scripts/federation_demo.py --cross-border
.venv/bin/python scripts/federation_demo.py --cross-border --no-forecast
.venv/bin/python scripts/federation_demo.py --brics
.venv/bin/python scripts/federation_demo.py --brics --no-forecast
```

`--brics` starts a South African node seeded with coal belt readings around
eMalahleni, Middelburg and Secunda, and a Brazilian node seeded with clearing
fires at Novo Progresso (Pará), Guarantã do Norte (Mato Grosso) and Candeias do
Jamari (Rondônia). Each shows its hotspots, its own authority table and its own
corridors, both feeds are shown to have the same shape, and a Delhi node lists
both as neighbours. With a model provider, each node then drafts one alert to
its own country's authority — Nkangala District under the Air Quality Act,
SEMAS under the fire law — and holds it for a person to confirm; nothing is
sent. `--no-forecast` skips those two model calls. The three processes differ
only in `VAYUDOOT_NODE_COUNTRY` and their seeded signals, and none of the nodes
is run by, or has been offered to, any government.

`--cross-border` adds a third node, configured as `country=PK`, with burning
seeded around Kasur, Raiwind and Sheikhupura in Pakistan's Punjab. Delhi
subscribes to both Punjabs and forecasts with both in hand. It shows the
contract working across a border — a Delhi instance consuming a Pakistani one
with no code changed. It does not claim that any Pakistani agency runs a node or
has been approached; the node is this application with `PK` in its
configuration, which is exactly what one would be.

The shipped upwind reach, 500 km, covers Lahore (428 km from Delhi) and
Sheikhupura (464 km) with no configuration change. It was 400 km until this run
showed that it stopped short of both.

## What this is not

**Not federated learning.** No model is trained, shared, averaged, or updated
across nodes. If that is built later it belongs beside this, not instead of it —
the feed is useful on the day it is switched on, and a shared model would not be.

**Not a consensus network.** Nodes do not vote, agree, or reconcile. Each is
authoritative for what it detected and no node can alter another's record.

**Not a trust system.** There is no signing, no allowlist of known-good nodes,
and no reputation. A node chooses which feeds to read, which is the only trust
decision the design makes, and it is made by an operator rather than by an
algorithm. If the network grew past a handful of nodes this is the first thing
that would need building.

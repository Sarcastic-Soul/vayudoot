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

## The contract

### `GET /node`

Who this instance is.

```json
{
  "node_id": "punjab-node",
  "name": "Punjab State Air Quality Cell",
  "region": "punjab",
  "instance_url": "https://punjab.example.org",
  "contact": "airquality@punjab.example.org"
}
```

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

## Trying it locally

`scripts/federation_demo.py` runs the whole thing on one machine: it starts a
second instance as a Punjab node with seeded stubble-burning signals, points a
Delhi node at its feed, and shows the Delhi forecast with and without the
neighbour. Two real processes, the real HTTP contract, no mocking.

```bash
.venv/bin/python scripts/federation_demo.py
```

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

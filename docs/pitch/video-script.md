# Demo video — shot-by-shot script

**Target: 4 minutes.** The brief allows 3–5. Four leaves room to speak at a
normal pace; the commonest failure in a hackathon video is rushing a five-minute
script into four and a half minutes of narration nobody can follow.

The narration below is about 600 words, which is four minutes at a calm
speaking pace. Read it aloud once before recording. Anything you stumble on,
cut — it is written to be spoken, not read.

| Shot | Time | What is on screen |
| --- | --- | --- |
| 1 | 0:00 – 0:30 | Deck slides 2 and 3: the problem, with sources |
| 2 | 0:30 – 1:00 | Operations view on the Punjab node, satellite layers on |
| 3 | 1:00 – 1:40 | One hotspot taken apart: signals, people in reach, the satellite reading |
| 4 | 1:40 – 2:10 | Alert the authority: review, confirm, sandbox envelope |
| 5 | 2:10 – 2:40 | The citizen path: one photograph |
| 6 | 2:40 – 3:35 | Cross-border: the network panel, the GeoJSON feed, the Lahore–Delhi outlook |
| 7 | 3:35 – 4:00 | Close on deck slides 10 and 11 |

---

## Before you record

**Three local nodes, seeded.** The new shots need a Punjab node with hotspots, a
node configured for Pakistan's Punjab, and a Delhi node that reads both feeds.
This is the same setup `scripts/federation_demo.py --cross-border` builds, left
running so a browser can look at it.

Run this once from the repo root. Everything it writes goes under
`/tmp/vd-demo`, so it cannot touch a real store.

```bash
.venv/bin/python - <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, "scripts")
from federation_demo import write_signal_store, BURNING_SITES, CROSS_BORDER_SITES
print("Punjab", write_signal_store(Path("/tmp/vd-demo/in-pb"), BURNING_SITES))
print("Pakistan Punjab", write_signal_store(Path("/tmp/vd-demo/pk-pb"), CROSS_BORDER_SITES))
PY
# Citizen cases, so the Punjab map also shows uncorroborated hotspots
mkdir -p /tmp/vd-demo/in-pb/cases && cp data/cases/*.json /tmp/vd-demo/in-pb/cases/ 2>/dev/null || true

node() {  # port id name region country neighbour-feeds
  R=/tmp/vd-demo/$2
  DATABASE_URL= VAYUDOOT_SCAN_ENABLED=false VAYUDOOT_PUBLISH_FEED=true \
  VAYUDOOT_NODE_ID=$2 VAYUDOOT_NODE_NAME="$3" VAYUDOOT_NODE_REGION="$4" \
  VAYUDOOT_NODE_COUNTRY=$5 VAYUDOOT_NODE_URL=http://127.0.0.1:$1 \
  VAYUDOOT_NEIGHBOUR_FEEDS="$6" \
  VAYUDOOT_CASE_DIR=$R/cases VAYUDOOT_UPLOAD_DIR=$R/uploads \
  VAYUDOOT_ALERT_DIR=$R/alerts VAYUDOOT_IMAGERY_DIR=$R/imagery \
  VAYUDOOT_SANDBOX_OUTBOX=$R/outbox \
    .venv/bin/uvicorn vayudoot.api:app --port $1 &
}
node 8001 in-pb "Punjab node" "Punjab" IN ""
node 8002 pk-pb "Pakistan Punjab node" "Punjab (Pakistan)" PK ""
node 8000 in-dl "Delhi node" "Delhi" IN \
  "http://127.0.0.1:8001/feed,http://127.0.0.1:8002/feed"
```

- Shots 2 to 5 use `http://localhost:8001/` (Punjab).
- Shot 6 uses `http://localhost:8000/#forecast` (Delhi).

**What it costs.** Shots 2, 3 and 6's network panel spend no model calls. The
alert in shot 4 is one Flash-Lite call. The satellite reading in shot 3 is one
Flash call, and it is cached per hotspot and image date, so a second take is
free. The corridor outlook in shot 6 is one Flash-Lite call per sampling point
(six for Lahore–Delhi). Draft the alert and the satellite reading once before
you record, so the take does not wait on the model — the page shows a cached
reading and a pending alert without calling again.

**If Gemini answers 503.** It happens on the free tier at busy hours; the
server walks its chain of free models and then says so plainly. Wait a minute
and press the button again. A corridor outlook that comes back with some
sampling points failed says so on screen ("1/6 answered, 5 waypoints failed") —
that is honest, but it is a weak take. Ask again later rather than record it.

**The live deployment** runs the scan for real, so `vayudoot.onrender.com`
carries whatever FIRMS actually detected that day. It is the stronger recording
for shot 2 when there is burning to see, but it is not reproducible, and it is
one node. Wake it a minute before you start; the free tier sleeps after 15
minutes idle.

Checklist:

- Browser at 1440×900, zoom 100%, bookmarks bar hidden, one tab only.
- Terminal font at least 16pt, if you show the terminal in shot 6.
- One photograph of a pollution event ready to upload for shot 5. Anything
  real: a waste fire, a construction site, a smoking exhaust.
- Close Slack, mail, and anything that shows notifications.
- **Do not** record with `VAYUDOOT_SCAN_ENABLED=true` — you do not want a
  background scan changing the map mid-take.

---

## Shot 1 — The problem (0:00 – 0:30)

**On screen:** the deck, slide 2, then slide 3 at about 0:18.

<!-- Every figure on slides 2 and 3 is sourced in sources.md. The narration
     deliberately says none of them aloud. -->

> India measures air quality at city scale. A station reports one number for a
> whole district — and most towns do not have one at all. It cannot see the
> waste fire behind one building, or the field burning upwind of a city that
> will be breathing it tomorrow.
>
> And smoke does not stop at a border. The two Punjabs are one paddy belt split
> by an international line. Across BRICS the shape repeats: coal on South
> Africa's Highveld, fire season in the Amazon.

*Hold each slide. Do not read the statistics aloud — they are on screen, with
their sources, and reading them wastes time.*

---

## Shot 2 — The map (0:30 – 1:00)

**On screen:** `http://localhost:8001/` — the operations view on the Punjab
node. Let the map finish drawing before you start talking.

> This is Vayudoot — what a state air quality cell opens in the morning. Every
> circle is a place where pollution is happening, built from every signal that
> agrees: a satellite fire detection, a ground station past the Indian standard,
> a citizen's photograph.

**Action:** open the **Satellite** control on the map. Turn on true colour,
aerosol and fires.

> These layers are yesterday's NASA pass, straight from GIBS — so the claim on
> the map can be held up against the sky it was made about.

**Action:** point at a card marked *Independently corroborated*.

> These were raised by satellite and station alone. No citizen was involved —
> because if only reports made hotspots, the map would be empty everywhere
> nobody had the app, and an empty map looks exactly like clean air.

---

## Shot 3 — Taking one apart (1:00 – 1:40)

**Action:** click the Ludhiana hotspot.

> Every hotspot can be taken apart. The circle is an area, never a pin, with a
> one-kilometre minimum — a circle drawn tight around one building is an
> accusation, and we never name anyone. Underneath it, every signal, with its
> time and its source.

**Action:** cursor to the *Who is in reach* card.

> About one point six million people live within ten kilometres. It says it is
> a coarse count, because it is one.

**Action:** scroll to *Satellite imagery*. The reading is already there.

> And here Gemini reads the actual satellite picture of this spot. Today it
> says: cloud over the centre, no plume visible — and it says that "not
> visible" is not "no smoke". This reading never raises the hotspot's
> confidence. A model looking at a 375-metre pixel is not independent evidence.

*Say what the reading on your screen says, not what this script says. It is a
real model call on a real picture, so it changes with the weather.*

---

## Shot 4 — Alert the authority (1:40 – 2:10)

**Action:** scroll to the alert. It is drafted and waiting.

> A corroborated hotspot can go straight to the authority — no citizen has to
> file first. The facts block is built by code; only the summary is the
> model's, and it is marked that way. It is addressed to the Punjab Pollution
> Control Board, in English and Punjabi.

**Action:** click **Confirm and send this alert**. Hold on the envelope.

> Nothing moves until a person confirms. And then it goes nowhere real: the
> address is on the reserved dot-invalid domain, the envelope is written to a
> sandbox outbox, and a test fails if anyone changes that. An uncorroborated
> hotspot cannot be alerted on at all.

---

## Shot 5 — The citizen path (2:10 – 2:40)

**Action:** click **Report**. Upload your photograph, drop the pin, submit. Cut
to the finished case.

> A satellite sees heat, not fuel. A citizen's photograph names what is
> burning. Gemini classifies it, three agents check it against satellite,
> station and wind data in parallel, the right authority is found for that
> exact spot, and a complaint is drafted in English and the local language —
> then it stops for a human to confirm.

*If the pipeline is slow, cut from submission to the finished case. Do not
narrate over a spinner.*

---

## Shot 6 — Across a border (2:40 – 3:35)

**On screen:** `http://localhost:8000/#forecast` — the Delhi node. Scroll to
**The network**.

> Smoke does not stop at a state line or a national one. This is a Delhi node.
> It has detected nothing itself. It reads two neighbours: a Punjab node, and a
> node configured for Pakistan's Punjab. Nobody in Pakistan runs this — it is
> the same software started with a different country code, which shows the
> contract works across a border.

**Action:** click the `/feed.geojson` card; the raw GeoJSON opens. Scroll a
second, then go back.

> Each node publishes what it detects on an open feed, and the same feed as
> standard GeoJSON — areas, never points, no reporter, no case ids. Any agency
> in any country can open it in QGIS without our code. What is shared is a
> detection layer, not model weights.

> The same contract carries nodes configured for South Africa's Highveld and
> Brazil's arc of deforestation — coal plants in one, forest fires in the other,
> each with its own country's authority table and air standard. Only the
> country code differs. No agency in either country runs them.

*For this line, `python scripts/federation_demo.py --brics --no-forecast`
starts both and shows Delhi reading them, with no model call.*

**Action:** back to the corridor list. Open **Lahore–Delhi trans-boundary smoke
corridor**.

> Then Delhi forecasts along the corridor, with both Punjabs' fires in hand.
> Gemini reads the wind forecast, the pollutant forecast and every hotspot
> within five hundred kilometres upwind, and reports a risk per sampling point
> with its reasons. It is labelled as a model's reasoning, never as an official
> forecast — and when a lookup fails, it says so instead of guessing.

> Every outlook is scored against what the stations later measured, next to
> two forecasts that use no model. On twenty-one past days, ours has not beaten
> them yet — it calls clean days too dirty — and the node says so on its own
> forecast page.

*If you prefer the terminal, `python scripts/federation_demo.py --cross-border`
tells the same story in about the same time.*

---

## Shot 7 — Close (3:35 – 4:00)

**On screen:** deck slide 10, then slide 11.

> Everything region-specific is data, not code. A state, an authority or a
> corridor is a JSON edit — even one that crosses a border.
>
> It runs on free tiers with no credit card: Gemini through AI Studio, one
> container, and public NASA and open-data sources. When one free Gemini model
> is busy, it moves to the next.
>
> Over five hundred tests, including ones whose job is to fail if somebody
> weakens a safety rule. It is live now, and the code is public.

**End card:** `vayudoot.onrender.com` and the GitHub URL. Hold three seconds.

---

## If a shot fails on the day

- **Gemini answers 503 or 429.** The free models are busy or the day's quota is
  spent. Shots 2, 3 (without the satellite reading) and the network half of
  shot 6 do not touch the model. Record those, and come back for the rest.
- **The map is empty.** The seed step did not run, or the server is reading
  Postgres. Check `DATABASE_URL=` is set empty in the command.
- **The network panel shows a neighbour as unreachable.** One of the three
  nodes did not start. That is a real state the panel is built to show, but it
  is not the take you want: restart the node.
- **FIRMS returns nothing real.** Expected in September — the burning season is
  October to November. The seeded signals exist so the demo does not depend on
  the weather.

## What not to say

Five claims would be wrong, and a judge who catches one stops believing the
rest:

- **Not** "it predicts air quality with a trained model." It is a model
  reasoning over public data, and it says so on every forecast it produces.
- **Not** "the nodes share their models" or "federated learning." They share a
  detection layer. Say detection layer.
- **Not** "it alerts the pollution board" as if something was delivered. It
  drafts, a human confirms, and the envelope goes to a sandbox outbox.
- **Not** "Pakistan runs a node", or any government. It is our software
  configured for Pakistan's Punjab, to show the feed works across a border.
- **Not** "the satellite reading confirms the fire." It is an annotation and
  never changes a hotspot's confidence.

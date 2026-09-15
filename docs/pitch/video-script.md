# Demo video — shot-by-shot script

**Target: 4 minutes.** The brief allows 3–5. Four leaves room to speak at a
normal pace; the commonest failure in a hackathon video is rushing a five-minute
script into four and a half minutes of narration nobody can follow.

Read the narration aloud once before recording. Anything you stumble on, cut —
it is written to be spoken, not read.

---

## Before you record

**Two ways to get a map with content, and they trade off against each other.**

*The live deployment* now runs the scan for real, so `vayudoot.onrender.com`
carries hotspots built from whatever FIRMS actually detected that day. That is
the stronger recording: nothing is seeded, and the narration about instruments
raising hotspots with no citizen involved is demonstrably true on screen. The
cost is that it is not reproducible — what is on the map is the weather, so a
good take cannot be retaken later. Wake the instance a minute before you start;
the free tier sleeps after 15 minutes idle and the first request takes 30 to 60
seconds.

*A local seeded store* is the reproducible option, and it is what produced the
screenshots in the deck. Use it if you want to record shot 4 repeatedly, or if
FIRMS is quiet.

To seed locally, run this once.

```bash
# from the repo root
mkdir -p /tmp/vd-demo/cases /tmp/vd-demo/signals /tmp/vd-demo/uploads
cp data/cases/*.json /tmp/vd-demo/cases/ 2>/dev/null || true

.venv/bin/python - <<'PY'
import json, sys
sys.path.insert(0, "scripts")
from federation_demo import seeded_signals
for i, s in enumerate(seeded_signals()):
    open("/tmp/vd-demo/signals/seed-%03d.json" % i, "w").write(json.dumps(s))
print("seeded", len(seeded_signals()), "signals")
PY

DATABASE_URL= VAYUDOOT_CASE_DIR=/tmp/vd-demo/cases \
VAYUDOOT_UPLOAD_DIR=/tmp/vd-demo/uploads VAYUDOOT_SCAN_ENABLED=false \
  .venv/bin/uvicorn vayudoot.api:app --port 8000
```

Then, in a second terminal, have this ready but **not yet run** — it is shot 5:

```bash
.venv/bin/python scripts/federation_demo.py
```

Checklist:

- Browser at 1440×900, zoom 100%, bookmarks bar hidden, one tab only.
- Terminal font size up — at least 16pt. Terminal text at default size is
  unreadable after video compression, and shot 5 is entirely terminal.
- Have one photograph of a pollution event ready to upload for shot 4. Anything
  real: a waste fire, a construction site, a smoking exhaust.
- Close Slack, mail, and anything that shows notifications.
- **Do not** record with `VAYUDOOT_SCAN_ENABLED=true` — you do not want a
  background scan changing the map mid-take.

---

## Shot 1 — The problem (0:00 – 0:35)

**On screen:** the deck, slide 2. Full screen.

> India monitors air quality at city scale. A station reports one number for a
> whole district — and it cannot see the waste fire behind one building, the
> stack venting at two in the morning, or the field burning forty kilometres
> upwind of a city that will be breathing it tomorrow.
>
> Those hyper-local events are most of what people actually breathe, and almost
> none of the data.
>
> And when somebody does notice one, acting on it takes hours: work out which of
> several overlapping authorities has jurisdiction at that exact spot, cite the
> right statute, file, then chase it for weeks. Almost nobody does it. The
> pollution continues because the paperwork defeats people, not because the law
> is missing.

*Hold slide 2 for the whole shot. Do not narrate the statistics — they are on
screen and reading them aloud wastes six seconds.*

---

## Shot 2 — The map (0:35 – 1:20)

**On screen:** `http://localhost:8000/` — the operations view. Let the map
finish drawing before you start talking.

> This is Vayudoot. It is what a state air quality cell opens in the morning.
>
> Every one of these is a place where pollution is happening, built from every
> signal that agrees — a satellite thermal detection, a ground station reading
> past the Indian standard, a citizen's photograph.

*Say the count you can actually see, and say it from the heading rather than
from this script. The number is whatever the store holds on the day, and on the
live deployment it is whatever is genuinely burning.*

**Action:** scroll the ranked list slowly so both kinds of card are visible.
Point the cursor at the green *Independently corroborated* band on a Punjab
card, then at an uncorroborated citizen one.

> Here is the decision the whole system turns on. The ones marked
> *independently corroborated* were raised by satellite and station evidence
> alone. **No citizen was involved at all.**
>
> That matters, because if only reports created hotspots, this map would be
> empty everywhere nobody had used the app — which is most of India. And an
> empty map looks exactly like clean air.
>
> The ones marked *citizen reports only* came from public submissions, and their
> confidence is capped at sixty per cent until something independent agrees.
> However many reports arrive. That
> is what stops fifteen coordinated fake reports from manufacturing a hotspot —
> and a public map that can be aimed at an address is a weapon, not a public
> good.

---

## Shot 3 — Taking one apart (1:20 – 2:00)

**Action:** click the first hotspot.

> A number on a map is an assertion, so every hotspot can be taken apart.

**Action:** pause on the map. Cursor along the circle's edge.

> The circle is the hotspot's published extent — never a pin. There is a one
> kilometre minimum, because a detection drawn tightly around one building is an
> accusation against whoever occupies it, whether or not you name them. We do
> not name them, ever.

**Action:** scroll to the signal list.

> And here is everything underneath it. Two satellite detections and a ground
> station reading, each with its time, how sure we are it is real, and how large
> the observed thing is.
>
> Those two are deliberately separate numbers. A model being certain of what it
> saw is not the same as what it saw being serious — we conflated them once, and
> a single clear photograph of a small fire came out as *severe*.

**Action:** cursor to the "Unidentified source" heading.

> The satellite says something is burning. It cannot say what — it sees heat,
> not fuel. Which is exactly where the citizen comes in.

---

## Shot 4 — The citizen path (2:00 – 2:50)

**Action:** click **Report** in the navigation. Upload your photograph, drop the
pin, submit. Let it run.

> A person standing in front of the problem photographs it. Gemini reads the
> image and classifies it — the pollution type, the severity, the visible
> indicators, and a calibrated confidence. Below a floor, it stops and asks for
> a human rather than guessing.
>
> Then three agents run in parallel against independent sources — NASA FIRMS,
> OpenAQ, and wind data — and back-trace the plume upwind. The photograph stops
> being an anecdote and becomes a measurement.
>
> Jurisdiction is resolved against a table covering all twenty-eight states and
> eight union territories. And Gemini drafts the formal complaint, in English
> and in the region's own language, citing the statute that authority actually
> works under.

**Action:** show the drafted complaint. Scroll to the local-language version.

> Then it stops. **Nothing is filed until a human confirms** — and in this build
> nothing reaches a real regulator at all. Every authority address in the
> repository is on the reserved dot-invalid domain, and there is a test that
> fails if anyone changes that. A prototype that can email a State Pollution
> Control Board during a demo is a liability, not a feature.

*If the pipeline is slow, cut from submission to the finished case. Do not
narrate over a spinner.*

---

## Shot 5 — Federation (2:50 – 3:35)

**On screen:** the terminal. Run `.venv/bin/python scripts/federation_demo.py`.

> Stubble smoke from Punjab reaches Delhi about a day and a half later. It is
> the best-documented pollution event in India, and it crosses a state boundary
> — which is exactly why no single-state system catches it.
>
> This starts two real instances. A Punjab node, and a Delhi node that has
> detected nothing of its own.

**Action:** let it reach section 3. Point at `hotspots offered: 3`.

> Punjab publishes what it found on an open feed. Delhi reads it over HTTP. No
> shared model, no central authority, no permission — a node id, a region, and a
> URL.
>
> And note what the feed does not carry: no signals, no case ids, nothing that
> identifies who reported anything.

**Action:** let the forecast print.

> Then Delhi forecasts, with Punjab's detections in hand. Gemini reads a wind
> forecast, a pollutant forecast, and every hotspot within four hundred
> kilometres upwind.
>
> Look closely at what it says here. It was handed three severe hotspots — and
> it checked them against the forecast wind, found the air is arriving from the
> south, and reported them as present and *not contributing*. It declined to
> blame them.
>
> That is the harder answer, and it is the correct one. Out of burning season
> the wind reverses; in October it would say the opposite.

---

## Shot 6 — Close (3:35 – 4:00)

**On screen:** deck slide 10, then slide 11.

> Everything region-specific is data, not code. Adding a state, an authority or
> a corridor is a JSON edit — which is what decides whether this becomes a
> national system or stays a Delhi demo.
>
> It runs entirely on free tiers with no credit card. Gemini through AI Studio,
> one container on Render, and public evidence APIs. A state agency can pilot
> this without raising a purchase order.
>
> Four hundred and fifty tests, including ones whose job is to fail if
> somebody weakens a safety rule.
>
> It is live now, and the code and the reasoning behind every constraint are in
> the repository.

**End card:** `vayudoot.onrender.com` and the GitHub URL. Hold three seconds.

---

## If a shot fails on the day

- **The forecast errors (502).** You are out of Gemini free-tier quota — 20
  Flash requests a day. Record shots 2, 3 and 5 anyway; shot 5's detection and
  feed sections do not touch the model. Come back tomorrow for shot 4.
- **The map is empty.** The seed step did not run, or the server is reading
  Postgres. Check `DATABASE_URL=` is set empty in the command.
- **FIRMS returns nothing real.** Expected in September — the burning season is
  October to November. The seeded signals exist precisely so the demo does not
  depend on the weather.

## What not to say

Three claims would be wrong, and a judge who catches one stops believing the
rest:

- **Not** "it predicts air quality with a trained model." It is a model
  reasoning over public data, and it says so on every forecast it produces.
- **Not** "the states share their models." They share a detection layer. Say
  detection layer.
- **Not** "it files complaints automatically." It drafts, and a human confirms.
  That is a designed property, not a missing feature — say so with some pride.

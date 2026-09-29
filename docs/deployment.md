# Deployment

**Constraint: free tier only, no credit card, nothing that bills.** Everything
below either has a genuine free tier or is already paid for. If a choice here
stops being free, replace it rather than paying for it.

Free tiers change. Verify the current terms of anything on this page before
relying on it; what follows is the reasoning, and the reasoning survives even
when a specific provider does not.

---

## Cost surface

There are only five things that could cost money.

| | Cost | Covered by |
| --- | --- | --- |
| Model inference | the only real one | Gemini free tier, through Google AI Studio |
| Compute to run the API | free tier | Render |
| Serving the web UI | free tier | Firebase Hosting, Spark plan |
| Storage | free tier | Cloud Firestore, Spark plan (Postgres or JSON files as alternatives) |
| The evidence APIs | free | FIRMS, OpenAQ, Open-Meteo, Nominatim |

### Inference

This is where the money actually goes, so the two-tier model split in
`config.py` is a cost control, not a style choice. A single report runs seven
agent invocations — evidence, three corroboration agents, their synthesis node,
jurisdiction, drafting — and about ten model calls, since an agent that uses a
tool spends one call deciding to and another reading the result. Only two of
those invocations, photograph reading and complaint drafting, run on the primary
model. Everything else is mechanical tool-call-and-summarise work on the cheap
tier.

Forecasting is on the fast tier too, and it is the one model call that happens
without a citizen having submitted anything.

**Gemini serves both tiers. That is a rule, not a tuning choice.** Hard
constraint 6 in `CLAUDE.md`: the event this is built for does not consider a
submission without Google AI, and the two primary calls — reading the photograph
and drafting the complaint — are the only inference anyone would call meaningful.
The agents themselves run on Google's Agent Development Kit (ADK).

The tier split lives *inside* Gemini: flash for the two primary calls,
flash-lite for the eight fast ones, which is why the 20-a-day flash quota is the
number to watch and not the total.

Earlier versions used Amazon Bedrock, then Ollama as a second provider, and the
Strands Agents SDK (an AWS project) as the agent framework. Bedrock went because
it bills (constraint 3); Ollama and Strands went so that nothing in the stack is
another cloud company's.

### The scan, which costs no inference at all

`scan.py` is the piece that makes the map non-empty, and it is worth being
precise about what it spends: nothing on a model. It calls FIRMS and OpenAQ
directly and hands the payloads to the converters in `hotspots.py`. No agent is
involved.

What it does spend is HTTP requests against the evidence APIs, on a schedule.
Thirty scan points at the shipped corridor set, two calls each, once an hour.
Both APIs are free, but free is not unlimited, and a deployed instance shares
that allowance with every forecast anyone asks for.

That is not hypothetical. The first live forecast after the scan was switched on
came back with the wind lookup rate limited:

> Wind forecast tool returned a 429 Too Many Requests error, so wind direction
> and stagnation data are unavailable.

The forecast handled it correctly — it reported the failure in its own `basis`,
lowered its confidence and declined to claim the upwind hotspots were
contributing — but a degraded outlook is still a degraded outlook. If an
instance is being demonstrated, raise `VAYUDOOT_SCAN_INTERVAL_MINUTES` first.
VIIRS passes roughly twice a day, so scanning every three hours loses nothing
real and leaves the quota for the thing a person is watching.

### There is no card, and it decides everything here

Google Cloud's free tier — the $300 trial and the Always Free products alike —
requires a Cloud Billing account, and that requires a card on file even though it
is not charged. There is no card. So the whole of Google Cloud proper is out:
Vertex AI, Cloud Run, Cloud Functions, Maps Platform, Speech-to-Text,
Text-to-Speech, Translation.

The Gemini API through Google AI Studio is the exception and the reason this
works at all: it needs a Google account, no card and no billing account. It is
the one mandatory piece, and it is the free one.

Firebase's **Spark** plan is the other exception. It needs no card either, and
two of its products fit this project: Hosting for the web UI and Cloud Firestore
for storage. The rest of Firebase that would help — Cloud Functions, and Cloud
Storage for Firebase for photographs — needs the paid Blaze plan, so it is out.
So is a Hosting rewrite to Cloud Run, which is the usual way to put an API
behind a Firebase domain. The BigQuery sandbox and Looker Studio complete the
free Google set, for analysis rather than serving.

Nothing in the event rules requires hosting on Google Cloud — only that Google AI
is integrated. The API therefore stays on Render, the one piece of compute no
free Google product can run.

1. **Gemini free tier** via Google AI Studio, with `GEMINI_API_KEY` set.
   The daily caps are the real budget: 20 requests a day on the flash tier, 500
   on flash-lite (also 15 requests/minute and 250,000 tokens/minute), and the
   pro models are paid. `errors.py` uses these exact numbers — for
   `gemini-3.5-flash-lite` specifically — when a report fails on quota, rather
   than a generic "try again" message; see that module for why.

   A report costs two primary requests (evidence and drafting) and roughly eight
   fast ones, so **one Flash model is about ten reports a day** and the primary
   quota is what runs out. The quota is per model, not per key, so the primary
   tier walks a chain of five Flash models (`MODEL_FALLBACKS` in `config.py`) and
   moves on when one answers 429, 503 or 404 — about fifty reports a day, still
   without a card. That is why the corroboration synthesis node sits on
   the fast tier despite doing judgement work: it would otherwise cut the daily
   budget by a third. Watch the primary number, not the total.

   Both tiers can be overridden without touching code:

   ```bash
   VAYUDOOT_MODEL_ID=gemini-3.8-flash        # primary; turns the chain off
   VAYUDOOT_MODEL_ID_FAST=gemini-3.5-flash-lite
   ```

Before deploying, check the container carries everything: the pack template, the
vendored ES modules and the authority table all ship in the wheel, and
`.dockerignore` excludes `docs/`, `tests/` and `scripts/` but not
`src/vayudoot/templates` or `src/vayudoot/web/vendor`. A missing authority table
once passed every test and would have shipped an empty lookup.

**Develop against the test fakes. Spend the daily quota on real runs only.**
The whole pipeline runs offline in `pytest` in half a second; a debugging
loop against a live provider will eat a day's reports before lunch.

### Compute

**Render, free web service, Docker runtime.** Chosen because it needs no credit
card, runs an arbitrary Docker image so FastAPI works unchanged, gives a public
HTTPS URL, and 750 free instance-hours a month is enough for one instance
running continuously. It spins down after 15 minutes idle and takes 30-60
seconds to wake on the next request — wake it before any live demo. Render
assigns the listen port at runtime through `$PORT`; the `Dockerfile`'s `CMD`
reads it, falling back to 7860 for a local `docker run`.

Former choice, and why it moved: **Hugging Face Spaces, Docker SDK** was the
original target and the Dockerfile is still shaped to run unmodified there. As
of this writing, creating a Docker-SDK Space requires a PRO subscription
($9/month) — only Static Spaces are free without a paid plan. That fails
constraint 3 in `CLAUDE.md`, so it is no longer the default. If Hugging Face
ever reopens free Docker Spaces, reverting is a one-line `CMD` change plus
setting `PORT=7860`, since the image itself did not have to change.

Rejected, and why:

- **Google Cloud Run** — the free tier is generous and would comfortably cover
  this, but it requires a billing account with a card. Out on the no-card rule.
- **Fly.io, Railway** — trial credits rather than a free tier.
- **Vercel Python functions** — a full pipeline run is far longer than a
  comfortable serverless request. Wrong shape for the workload.

### Frontend

**Firebase Hosting for the public URL, and still served by FastAPI too.** The
web UI is static files with no build step, so the same directory,
`src/vayudoot/web`, is both what FastAPI mounts and what `firebase.json`
publishes. Firebase's CDN answers the page instantly even while Render's
instance is asleep, and the page says so ("Waking the server") rather than
showing an empty map for a minute.

What the split costs is one cross-origin hop. Spark cannot proxy a path to an
outside host, so a page served from a Firebase domain calls the Render API
directly: `web/config.js` sets the API base when the page's host ends in
`.web.app` or `.firebaseapp.com`, and leaves it empty everywhere else, so the
same files still work same-origin when FastAPI serves them. The API allows the
Firebase origins through `VAYUDOOT_CORS_ORIGINS`, and allows none by default.

### Storage

Cases are JSON files under `data/cases/` when nothing else is configured. On a
free container that disk is ephemeral: a restart or a rebuild loses them. Fine
for a demo, not for anything else — which is why `store.py` has two more
backends.

**Cloud Firestore** is the one this deployment uses, chosen when
`FIREBASE_SERVICE_ACCOUNT` is set. Spark gives 1 GiB stored, 50,000 document
reads and 20,000 writes a day, and `firestore_store.py` is built around those
two numbers: the one API process keeps an in-memory copy of what it has read and
writes through to Firestore, so map views cost no reads at all after the first,
and signals are grouped into day documents so an hourly scan costs a few writes
rather than one per observation. A cold start reads each collection once. The
catch is that there must be one writing process — see the module docstring
before running more than one worker. Unlike a free Postgres, Firestore does not
pause when idle.

**Postgres** is the alternative, chosen when `DATABASE_URL` is set and
`FIREBASE_SERVICE_ACCOUNT` is not: cases become rows, `data` as `jsonb`, on any
standard Postgres. Neon and Supabase both have free tiers with no card; both
pause after a stretch of inactivity, so wake one before a demo alongside the
compute host.

Photographs, voice notes and cached satellite imagery stay on the container's
disk whichever backend is chosen, because the free way to keep files, Cloud
Storage for Firebase, now needs the Blaze plan. A redeploy therefore keeps every
case but loses its photograph: the photograph URL answers 404, "Photograph is no
longer available", and the rest of the case is intact.

### Analytics (optional): BigQuery sandbox

`scripts/export_bigquery.py` writes signals, hotspots (as area polygons),
neighbours' hotspots, alert statuses and the corridors as newline-delimited
JSON with BigQuery schemas, and loads them into a BigQuery **sandbox** project
when `google-cloud-bigquery` (the `[bigquery]` extra), application default
credentials and a project id are all present. The sandbox needs no billing
account and no card: 10 GiB of storage, 1 TiB of queries a month, and every
table is deleted after 60 days. It does not allow streaming inserts or DML, so
the export uses load jobs only and appends snapshots that views deduplicate.
Nothing in the server depends on it. Setup, tables and queries:
`docs/bigquery.md`, which also builds a **Looker Studio** dashboard over the
tables. Looker Studio is free, needs no card, and reads the sandbox through its
own BigQuery connector.

### Evidence APIs

| Source | Terms |
| --- | --- |
| NASA FIRMS | free, key by email |
| OpenAQ v3 | free, key on registration |
| Open-Meteo | free for non-commercial use, no key |
| Nominatim | free, requires an identifying User-Agent and at most one request per second |

Nominatim's rate limit is a real condition of use, not a suggestion. The tool
sends a proper User-Agent already. If reverse geocoding ever moves into a loop,
cache it.

---

## Deploying to Render

1. Create a Web Service from the repo, runtime **Docker**, plan **Free**.
2. Render builds `Dockerfile` as-is and binds the container to the `$PORT` it
   assigns; nothing to configure there.
3. Set every secret from `.env.example` as an environment variable in the
   service's Environment tab. **Never commit a `.env`.**
4. Confirm `GET /health` reports the expected model and, critically, that
   `live_filing` is `false`.

## Setting up Firebase

One Firebase project serves both the web UI and the store. Everything below is
on the free Spark plan; if the console offers to upgrade to Blaze, decline.

### The project

1. Go to <https://console.firebase.google.com/>, **Create a project**, and
   decline Google Analytics (nothing here uses it). The project id it gives you,
   for example `vayudoot-4f2a1`, is used below.
2. Put that id in `.firebaserc` in place of the placeholder `vayudoot`.

### Firestore

1. In the console, **Build > Firestore Database > Create database**. Choose
   **Production mode** — the server reaches Firestore with a service account,
   which security rules do not restrict, and production mode denies every
   browser client, which is right because the web UI never talks to Firestore.
   Pick the location closest to the Render region; it cannot be changed later.
2. **Project settings > Service accounts > Generate new private key.** This
   downloads a JSON key. Treat it like a password: never commit it, and never
   paste it anywhere public.
3. In Render's Environment tab, add `FIREBASE_SERVICE_ACCOUNT` and paste the
   whole JSON file as its value. (Locally, the variable may instead hold the
   file's path.) Remove `DATABASE_URL` or leave it; Firestore wins when both
   are set.
4. Redeploy, open the map once, and check the console: collections `cases`,
   `signals`, `alerts` and `forecasts` appear as data is written. Each document
   holds the object as JSON text in a `json` field, and signals are grouped by
   day under ids like `2026-09-29-3`; see `firestore_store.py` for why.

Moving existing data across is not automated. Cases on the old store stay there;
a Firestore deployment starts with an empty map until the next scan.

### Hosting

1. Install the CLI and sign in: `npm install -g firebase-tools`, then
   `firebase login`.
2. From the repository root: `firebase deploy --only hosting`. It publishes
   `src/vayudoot/web` as configured in `firebase.json` and prints the site's
   URLs, `https://PROJECT_ID.web.app` and `https://PROJECT_ID.firebaseapp.com`.
3. In Render, set `VAYUDOOT_CORS_ORIGINS` to both of those URLs, comma
   separated, and redeploy the API. Until this is done the page loads but every
   API request fails, and the wake-up note stays on screen.
4. If the API is not at `https://vayudoot.onrender.com`, change the one URL in
   `src/vayudoot/web/config.js` and deploy hosting again.

Hosting serves the files exactly as they are in the repository, so a change to
the web UI needs `firebase deploy --only hosting` as well as the Render deploy.
`firebase.json` marks the app's own files `no-cache` so a deploy is seen at
once; only the vendored libraries are cached for a week.

## Pre-demo checklist

- [ ] Wake the service, and the database if Postgres is in use. Render's free
      instance sleeps after 15 minutes idle and the first request takes 30-60
      seconds. Opening the Firebase URL does it, and says so while it waits
- [ ] `GET /health` returns the expected model and `live_filing: false`
- [ ] `GET /hotspots` is **not empty**. An empty map is the worst thing a viewer
      can be shown, and it looks identical to clean air. If it is empty, either
      the scan has not run or no store is configured (`FIREBASE_SERVICE_ACCOUNT`
      or `DATABASE_URL`) and the JSON files were wiped by the last spin-down
- [ ] `GET /forecast?lat=&lon=` returns 200 rather than a 429-degraded outlook
- [ ] Credits or free-tier quota confirmed to have headroom
- [ ] One full run completed today, since a stale deployment is the usual failure
- [ ] Outbox reachable, so the filed complaint can actually be shown

What is on the map on the day is whatever is actually burning that day, because
the scan reads live FIRMS data. That is a stronger demonstration than seeded
signals and it is not reproducible, so a good take is worth keeping.

### Warming the model calls

The Gemini free tier answers 503 for long stretches, so every model call the
demo shows should be made before recording. `scripts/demo_prep.py` does it
against a running node: it seeds the demo hotspots if they are missing, reads
the demo hotspot's satellite image, drafts its alert, and warms the Delhi and
corridor forecasts, retrying 503s with backoff. It asks the free read first
every time, so running it twice spends nothing twice, and it can only POST the
imagery read and the alert draft — it never confirms or files anything.

    # server started with VAYUDOOT_FORECAST_CACHE_MINUTES=240, DATABASE_URL= and
    # VAYUDOOT_SCAN_ENABLED=false, then:
    .venv/bin/python scripts/demo_prep.py --dry-run
    .venv/bin/python scripts/demo_prep.py

Forecasts live in the server's memory, so a restart after prep empties them.
Seeding writes into the JSON store, so it works on a local node, not one on
Postgres. The checklist it prints ends with the exact command for each item
still cold.

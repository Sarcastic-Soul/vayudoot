# Deployment

**Constraint: free tier only, no credit card, nothing that bills.** Everything
below either has a genuine free tier or is already paid for. If a choice here
stops being free, replace it rather than paying for it.

Free tiers change. Verify the current terms of anything on this page before
relying on it; what follows is the reasoning, and the reasoning survives even
when a specific provider does not.

---

## Cost surface

There are only four things that could cost money.

| | Cost | Covered by |
| --- | --- | --- |
| Model inference | the only real one | Gemini free tier (Ollama offline, for development) |
| Compute to run the service | free tier | Render |
| Storage | free tier | Neon Postgres (JSON files if `DATABASE_URL` is unset) |
| The evidence APIs | free | FIRMS, OpenAQ, Open-Meteo, Nominatim |

### Inference

This is where the money actually goes, so the two-tier model split in
`config.py` is a cost control, not a style choice. A single report runs six agent
invocations. Four of them are mechanical tool-call-and-summarise steps and run on
the cheap tier; only photograph reading and complaint drafting use the primary
model.

**Gemini serves both tiers. That is a rule, not a tuning choice.** Hard
constraint 6 in `CLAUDE.md`: the event this is built for does not consider a
submission without Google AI, and the two primary calls — reading the photograph
and drafting the complaint — are the only inference anyone would call meaningful.
Putting them on Ollama would put that inference on a non-Google model.

```bash
VAYUDOOT_MODEL_PROVIDER=gemini   # primary: evidence, drafting  -> flash
VAYUDOOT_MODEL_PROVIDER_FAST=    # empty: fast tier follows      -> flash-lite
```

An earlier configuration split the tiers across two providers, with the
judgement calls on Ollama Cloud and the mechanical ones on Gemini flash-lite, to
spread one report across two free tiers. That is no longer available. What it was
buying is still worth having, so the tier split stays *inside* Gemini: flash for
the two primary calls, flash-lite for the eight fast ones, which is why the
20-a-day flash quota is the number to watch and not the total.

Amazon Bedrock was removed earlier for a different reason: it bills, and
constraint 3 says a dependency has to be free or already paid for.

### There is no card, and it decides everything here

Google Cloud's free tier — the $300 trial and the Always Free products alike —
requires a Cloud Billing account, and that requires a card on file even though it
is not charged. There is no card. So the whole of Google Cloud proper is out:
Vertex AI, Cloud Run, Cloud Functions, Maps Platform, Speech-to-Text,
Text-to-Speech, Translation.

The Gemini API through Google AI Studio is the exception and the reason this
works at all: it needs a Google account, no card and no billing account. It is
the one mandatory piece, and it is the free one.

Nothing in the event rules requires hosting on Google Cloud — only that Google AI
is integrated. The deployment therefore stays on Render.

1. **Gemini free tier** via Google AI Studio. `VAYUDOOT_MODEL_PROVIDER=gemini`.
   The daily caps are the real budget: 20 requests a day on the flash tier, 500
   on flash-lite (also 15 requests/minute and 250,000 tokens/minute), and the
   pro models are paid. `errors.py` uses these exact numbers — for
   `gemini-3.5-flash-lite` specifically — when a report fails on quota, rather
   than a generic "try again" message; see that module for why.

   A report costs two primary requests (evidence and drafting) and roughly eight
   fast ones, so **the free tier is about ten reports a day** and the primary
   quota is what runs out. That is why the corroboration synthesis node sits on
   the fast tier despite doing judgement work: it would otherwise cut the daily
   budget by a third. Watch the primary number, not the total.

   Both tiers can be overridden without touching code:

   ```bash
   VAYUDOOT_MODEL_ID=gemini-3.5-flash        # primary
   VAYUDOOT_MODEL_ID_FAST=gemini-3.5-flash-lite
   ```

2. **Ollama, the offline path.** Not the shipped provider. It is here for two
   reasons worth keeping: developing and running the eval harness without
   spending a metered quota, and the claim that a state could run this on its own
   hardware, which is part of the deployability argument rather than a
   convenience. `VAYUDOOT_MODEL_PROVIDER=ollama` with
   `OLLAMA_HOST=https://ollama.com` and a key from
   <https://ollama.com/settings/keys>.

   This is the only free option that can serve *both* primary agents, because
   `gemma4:31b` reads images and carries 256K of context. That matters: the
   evidence stage needs a multimodal model, and neither Groq's free tier nor a
   laptop without a GPU offers one. The defaults are the cloud model ids for
   that reason.

   The quota is published as session and weekly percentages rather than request
   counts, so treat it as opaque and watch the meter in the Ollama console.
   Since there is no number to check a report against, `callbudget.py` adds a
   safety cap of its own — generous defaults so real use and the test suite
   never reach it, there only to stop a bug from silently burning the whole
   session or week. It is a backstop, not a substitute for watching the meter.

   The same provider also drives a local daemon — set
   `OLLAMA_HOST=http://localhost:11434`, drop the key, and override both model
   ids. That needs a GPU to host a vision model; without one the evidence stage
   is the part that suffers first.

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

**Served by the same FastAPI process.** Mount the built static files and be done.
One deployment, one URL, no CORS configuration, no second free tier to keep
alive. Splitting the frontend onto Vercel or Pages buys nothing at this size and
costs a moving part.

### Storage

Cases are JSON files under `data/cases/` when `DATABASE_URL` is unset. On a
free container that disk is ephemeral: a restart or a rebuild loses them. Fine
for a demo, not for anything else — which is why `store.py` supports a second
backend: set `DATABASE_URL` to any standard Postgres connection string and
cases become rows instead, `data` as `jsonb`. Nothing in `store.py` is
provider-specific; **Neon** is what this deployment actually uses, chosen for
its free tier with no card, but Supabase's free Postgres works exactly the
same way. Either one pauses after a stretch of inactivity, so wake it before a
demo alongside the compute host.

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
4. Confirm `GET /health` reports the expected provider and, critically, that
   `live_filing` is `false`.

## Pre-demo checklist

- [ ] Wake the service, and the database if one is in use
- [ ] `GET /health` returns the expected provider and `live_filing: false`
- [ ] Credits or free-tier quota confirmed to have headroom
- [ ] One full run completed today, since a stale deployment is the usual failure
- [ ] Outbox reachable, so the filed complaint can actually be shown

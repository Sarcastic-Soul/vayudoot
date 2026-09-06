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
| Model inference | the only real one | AWS credits; Gemini free tier; Ollama locally |
| Compute to run the service | free tier | Hugging Face Spaces |
| Storage | free tier | JSON on disk; Supabase if it needs to persist |
| The evidence APIs | free | FIRMS, OpenAQ, Open-Meteo, Nominatim |

### Inference

This is where the money actually goes, so the two-tier model split in
`config.py` is a cost control, not a style choice. A single report runs six agent
invocations. Four of them are mechanical tool-call-and-summarise steps and run on
the cheap tier; only photograph reading and complaint drafting use the primary
model.

Two providers, both free tiers with no card. Amazon Bedrock was removed: it
bills, and constraint 3 in `CLAUDE.md` says a dependency has to be free or
already paid for.

**Neither free tier is used alone.** A report makes two primary calls and about
eight fast ones, and the two tiers can run on different providers, so the shipped
configuration splits them:

```bash
VAYUDOOT_MODEL_PROVIDER=ollama        # primary: evidence, drafting
VAYUDOOT_MODEL_PROVIDER_FAST=gemini   # fast: corroboration, jurisdiction
```

Ollama Cloud takes the two calls that need judgement, including the only one that
reads an image. Gemini's flash-lite tier takes the eight mechanical ones, where
500 requests a day is roughly sixty reports and nothing is spent from Ollama's
opaque session budget. Gemini's flash tier, the 20-a-day one, is then not used at
all — which is the point of the split.

1. **Gemini free tier** via Google AI Studio. `VAYUDOOT_MODEL_PROVIDER=gemini`.
   The daily caps are the real budget: 20 requests a day on the flash tier, 500
   on flash-lite, and the pro models are paid.

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

2. **Ollama Cloud free tier.** `VAYUDOOT_MODEL_PROVIDER=ollama` with
   `OLLAMA_HOST=https://ollama.com` and a key from
   <https://ollama.com/settings/keys>.

   This is the only free option that can serve *both* primary agents, because
   `gemma4:31b` reads images and carries 256K of context. That matters: the
   evidence stage needs a multimodal model, and neither Groq's free tier nor a
   laptop without a GPU offers one. The defaults are the cloud model ids for
   that reason.

   The quota is published as session and weekly percentages rather than request
   counts, so treat it as opaque and watch the meter in the Ollama console.

   The same provider also drives a local daemon — set
   `OLLAMA_HOST=http://localhost:11434`, drop the key, and override both model
   ids. That needs a GPU to host a vision model; without one the evidence stage
   is the part that suffers first.

**Develop against the test fakes. Spend the daily quota on real runs only.**
The whole pipeline runs offline in `pytest` in half a second; a debugging
loop against a live provider will eat a day's reports before lunch.

### Compute

**Hugging Face Spaces, Docker SDK, free CPU tier.** Chosen because it needs no
credit card, runs an arbitrary Docker image so FastAPI works unchanged, gives a
public HTTPS URL, and does not expire. It sleeps after a stretch of inactivity
and takes a moment to wake — wake it before any live demo.

Fallback: **Render**, free web service. Same shape, spins down when idle with a
slower cold start.

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

Cases are JSON files under `data/cases/`. On a free container that disk is
ephemeral: a restart or a rebuild loses them.

That is acceptable for a demo and not acceptable for anything else. When cases
need to survive, **Supabase free Postgres** is the upgrade — no card, and it only
means rewriting `store.py`, which exists precisely so that this is a
one-module change. Note that a free Supabase project pauses after a stretch of
inactivity, so wake it before a demo too.

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

## Deploying to Hugging Face Spaces

1. Create a Space, SDK **Docker**, visibility public.
2. Add a `Dockerfile` that installs the project and runs
   `uvicorn vayudoot.api:app --host 0.0.0.0 --port 7860`. Spaces expect port 7860.
3. Set every secret from `.env.example` as a Space secret. **Never commit a
   `.env`.**
4. Confirm `GET /health` reports the expected provider and, critically, that
   `live_filing` is `false`.

## Pre-demo checklist

- [ ] Wake the Space, and the database if one is in use
- [ ] `GET /health` returns the expected provider and `live_filing: false`
- [ ] Credits or free-tier quota confirmed to have headroom
- [ ] One full run completed today, since a stale deployment is the usual failure
- [ ] Outbox reachable, so the filed complaint can actually be shown

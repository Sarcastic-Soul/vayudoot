# How good is the forecast?

The forecast is Gemini (flash-lite, the `fast` tier) reading an Open-Meteo
pollutant forecast, an Open-Meteo wind forecast and the fire hotspots in reach,
then choosing one of four risk bands for the next 72 hours. Until now nobody had
checked it against what happened. This page reports two checks:

- a **backtest** on past days, run once on 29 September 2026 with
  `scripts/forecast_backtest.py`, and
- the **forecast ledger** (`src/vayudoot/ledger.py`), which records every live
  forecast and scores it once its window has passed. It has no results yet.

Short answer: **on 21 past cases the agent did not beat either baseline.
Carrying yesterday forward was right more often.** The agent over-calls clean
days, and that comes from the prompt. In the burning season around Delhi it was
about as good as the baselines and caught some bad days they missed, but the
sample is too small to call that a real difference.

## What "right" means

Each forecast is judged on the worst 24-hour mean of PM2.5 measured during its
72-hour window, by up to three OpenAQ reference monitors within 25 km (median
across stations, hour by hour). That value is put in a band:

| Band | PM2.5 (24-hour mean, µg/m³) | PM10 |
|---|---|---|
| low | up to 60 | up to 100 |
| elevated | 60 to 120 | 100 to 350 |
| high | 120 to 250 | 350 to 430 |
| severe | over 250 | over 430 |

The prompt gives no numbers for its bands. Its only anchor is "the standard",
which the tool prints next to every value. So `low` means within the Indian
24-hour standard (60 for PM2.5), and the higher edges follow the CPCB AQI
breakpoints. The reasoning is in `ledger.BAND_LIMITS`. Every case in the
backtest had PM2.5, so PM10 was never used.

A day needs 16 measured hours to count. A window needs at least two of its three
days. A case with no active reference monitor within 25 km, or too few hours, is
**unscorable**, and it is left out rather than counted as right or wrong.

Every method is scored on exactly the same cases:

- **agent**: the real forecast agent, with the real prompt and tools.
- **persistence**: the band of the 24 hours before the issue time, carried
  forward. It reads only stations, and only the past.
- **CAMS**: the Open-Meteo (CAMS global) forecast for the window, turned into
  24-hour means and banded by the same rule, with no model involved.

"Exact" is the share of cases where the band was right. "Within one" allows one
band either way. "Bias" is the average number of bands called above (+) or
below (−) what was observed. Brackets give a 95% Wilson interval. The paired
count ("agent only right 5, persistence only right 11") counts cases where one
method was right and the other was not, and p is an exact two-sided sign test
on those cases.

## What was run

**Cases.** 20 Indian cities on 26 issue dates, making 520 cases:

- Delhi, Ghaziabad and Gurugram (NCR).
- Ludhiana, Amritsar, Patiala, Bathinda, Jalandhar, Chandigarh and Hisar
  (Punjab and Haryana).
- Lucknow, Kanpur, Patna, Jaipur, Kolkata, Mumbai, Ahmedabad, Hyderabad,
  Bengaluru and Chennai.

The dates were every third day from 15 October to 26 November 2025 (the burning
season, 15 dates, so no two windows overlap), plus 11 dates from December 2025
to August 2026.

- 508 cases could be scored and 12 could not: 7 in Hisar, 3 in Bathinda and one
  each in Ludhiana and Amritsar, all because too few hours were reported.
- Of the 508, 433 also had a persistence value. The rest were mostly four dates
  (27 October, 21 January, 4 February and 6 May) when OpenAQ has almost no
  hours for the day before, in nearly every city.
- Observed bands across the 508 were: low 188, elevated 233, high 75,
  severe 12.

**Agent sample.** The agent was run on 21 of those cases. The cap was about 60
model requests, because the free tier (15 requests a minute, a daily cap) is
shared with the rest of the project. Each forecast took 2 requests. Three
attempts failed with Gemini 503 "high demand" errors, and one with a
per-minute 429.

The cases were picked in a fixed random order that spreads them across groups,
using only whether a case could be scored and had both baselines, never what
was observed. That gave 12 burning-season cases in NCR, Punjab and Haryana, 4
burning-season cases elsewhere, and 5 from the rest of the year. The model was
`gemini-3.5-flash-lite` on every case, and the forecaster was version 2 with
prompt hash `f41750678a0e…`.

## Results

### Baselines on every scorable case (no model)

| Group | n | Persistence exact | CAMS exact | Persistence bias | CAMS bias |
|---|---|---|---|---|---|
| All | 433 | 0.72 [0.67–0.76] | 0.51 [0.47–0.56] | −0.18 | −0.05 |
| Burning season, NCR and Punjab-Haryana | 131 | 0.65 [0.56–0.73] | 0.43 [0.35–0.51] | −0.21 | −0.37 |
| Burning season, elsewhere | 141 | 0.69 [0.61–0.77] | 0.64 [0.56–0.71] | −0.18 | −0.16 |
| Rest of the year | 161 | 0.79 [0.72–0.84] | 0.47 [0.40–0.55] | −0.16 | +0.30 |

Within one band: persistence 0.97, CAMS 0.94.

Yesterday's air is a strong forecast of the next three days' worst day in
Indian cities, and it is hard to beat. Raw CAMS is well behind. It reads too low
around Delhi and Punjab in the burning season (bias −0.37) and too high the rest
of the year (+0.30).

### The agent, on the same 21 cases

| Method | Exact | Within one | Bias |
|---|---|---|---|
| Agent | 0.38 [0.21–0.59] | 0.95 | +0.43 |
| Persistence | 0.67 [0.45–0.83] | 0.91 | −0.33 |
| CAMS | 0.52 [0.32–0.72] | 0.95 | −0.24 |

- Agent against persistence: agent only right 5, persistence only right 11,
  p = 0.21.
- Agent against CAMS: agent only right 4, CAMS only right 7, p = 0.55.

By group, exact rate:

| Group | n | Agent | Persistence | CAMS |
|---|---|---|---|---|
| Burning season, NCR and Punjab-Haryana | 12 | 0.42 | 0.50 | 0.50 |
| Burning season, elsewhere | 4 | 0.50 | 0.75 | 0.50 |
| Rest of the year | 5 | 0.20 | 1.00 | 0.60 |

What the agent called (rows) against what was observed (columns):

| called \ observed | low | elevated | high | severe |
|---|---|---|---|---|
| low | 0 | 1 | 0 | 0 |
| elevated | 4 | 4 | 1 | 0 |
| high | 0 | 4 | 4 | 1 |
| severe | 1 | 0 | 1 | 0 |

### What this says, and what it does not

- **The agent adds nothing measurable overall.** It was right less often than
  persistence and CAMS. None of the differences is statistically significant,
  and with 21 cases they could not be. Twenty-one cases can show a large
  failure. They cannot show a small edge in either direction.
- **It never called a clean day clean.** All five observed-`low` cases were
  called `elevated` (four) or `severe` (one). Hisar on 8 April 2026 was called
  severe at confidence 0.85, and it measured 23 µg/m³. Its stated drivers were a
  north-north-westerly wind from hotspots, 20 stagnant hours, and "modelled
  PM2.5 and PM10 heavily exceeding the standards". Its basis quoted an hourly
  peak of 286 µg/m³ PM2.5 and 3,085 µg/m³ PM10 (a dust spike). The CAMS worst
  24-hour mean for the same window was 119 µg/m³, and yesterday's measured
  mean was 23.
- **Where it helped, it helped on the days that matter.** Delhi on 27 October
  and Gurugram on 8 November 2025 were `high`. Both baselines said `elevated`,
  and the agent said `high`, giving fires upwind and still air as the reason.
  Its bias in the burning-season NCR and Punjab group was +0.08, against −0.67
  for persistence and −0.42 for CAMS. So it missed less in the direction that
  hurts people. That is a hint worth testing on more cases, not a finding.

## Why it over-calls: problems found in the forecaster

1. **The prompt pushes every calm day to `elevated`.** It says: "Still air with
   no upwind fire is still a reason for an elevated outlook." Most Indian city
   forecasts have some stagnant hours, so `low` is almost never chosen. This
   matches the confusion matrix above. Jaipur on 3 June 2026 had no hotspot
   in reach at all, and the agent still said `elevated`.
2. **The prompt gives the bands no numbers.** "Use severe only when the forecast
   is far past the standard" leaves the model to decide what "far" means. The
   tool also gives it *hourly peaks* and "hours above standard", while the
   standard is a 24-hour mean. A single peak hour at 150 reads as "far past 60"
   even when the day's mean is inside the standard.
3. **Hotspots were shown without a count** (fixed in this branch, commit
   "tell the forecast how many hotspots are in reach"). Only the nearest ten
   were listed, so the model could not tell ten fires from a thousand.
   Bathinda on 11 November 2025 had 1,221 hotspots in reach. The prompt now counts every
   hotspot by direction. The backtest ran with this fix in place.
4. **Found and fixed earlier in this branch.**
   - Corridor forecasts only ever ran one waypoint.
   - The tools read their window from midnight UTC instead of now.
   - The dominant wind was an arithmetic mean of compass bearings. In a live
     Mumbai case, hours blowing from 9° to 356° (all near north) averaged to
     151° (south-south-east).
5. **Not fixed here.** The live `tools/openaq.py` takes the first station
   OpenAQ lists, which in Delhi can be one that stopped reporting in 2018. The
   ledger's own `observe()` checks each station is active. The live tool should
   do the same.

The prompt was not changed. The first two problems suggest a clear change:
state the band edges on 24-hour means, and remove the "still air alone means
elevated" rule. But a changed prompt has a new hash and needs its own
evaluation. Doing that now would have spent a second share of the shared free
tier on the same day. The backtest caches everything, so after a prompt change
`python scripts/forecast_backtest.py` re-asks only the model, on the same 21
cases first.

## How far to trust the backtest

**Leakage: the air-quality input is not a true forecast.** Open-Meteo keeps no
past runs of its CAMS air-quality forecast. Its `_previous_dayN` variables come
back empty, and its `run=` parameter is refused. The only past series is an
archive stitched from the first hours of successive CAMS runs. So the value for
hour 48 of a window comes from a run started near hour 48, not from a 48-hour
forecast, which makes it closer to an analysis than a forecast.

Both the agent and the CAMS baseline read this archive. The comparison between
them is therefore fair, but both look better than they would live. Persistence
reads nothing after the issue time and does not leak. That makes the result
harder on persistence than on the other two, and persistence still came out
ahead.

**Wind is an honest forecast.** Wind comes from Open-Meteo's Single Runs API:
one ECMWF IFS run, started at 12:00 UTC the day before the 00:00 UTC issue time,
and published before it. Each case records which run it used. Where that run is
missing, the script falls back to an older run, never a newer one.

**Fires are fuller than a live node sees.** The hotspots come from NASA FIRMS
VIIRS for the two days before the issue time, over the whole 500 km reach. The
standard-processing product was used up to June 2026, and near-real-time after
that. A live node sees only what its scan points found. So this gives the model
more fire information than production does, which should help it, and it still
did not win.

**Memory.** Dates in the tool output are moved forward 364 days, so the weekday
is kept. The prompt carries no date. The model could still know the climate,
for example that Delhi is smoggy in November, but a live forecaster knows that
too.

**The sample is small and not independent.**

- Twenty-one agent cases give intervals about ±0.2 wide.
- The three NCR cities are 15 to 25 km apart, so their stations overlap.
- The burning season is 15 dates, so cases on the same day across cities share
  one weather pattern.
- The baseline table (433 cases) is much firmer than the agent table.

**The observation is not the model's own target.** The forecast is asked about
"the next 72 hours" with no stated statistic. Scoring on the worst 24-hour mean
is our choice: it is what the bands are defined on, and it is what an authority
acts on. A model reading hourly peaks will score worse against a daily-mean
target than against an hourly one. That is part of the problem described above,
and does not excuse it.

## The ledger

Every forecast served live, whether for a point or for each waypoint of a
corridor, is now written down when it is made. The record holds:

- its band, window and place
- the forecaster version and prompt hash
- the model id
- the raw CAMS worst day for the same window, fetched at the same moment

Once the window has closed (plus 6 hours for stations to report), the scan timer
scores it by the rule above, with no model call. `GET /forecasts/ledger` lists
the records, and `GET /forecasts/skill` gives the same comparison as this page:
exact and within-one rates, a confusion matrix, and both baselines on the same
forecasts. It counts only the forecaster now running.

The ledger cannot leak: the forecast and its CAMS baseline are fixed before
anything is observed. Over a season it will give a firmer answer than this
backtest. Until it holds at least 30 scored forecasts, its own caveat calls the
figures an anecdote.

## Reproducing

```
uv run python scripts/forecast_backtest.py --max-calls 0    # baselines only, no model
uv run python scripts/forecast_backtest.py --max-calls 60   # add up to 60 model requests
```

Everything fetched, and every model answer, is cached under `data/backtest/`
(git-ignored). A rerun spends nothing unless the prompt or the forecaster
version changed. `data/backtest/results.json` has every case, with station
names, observed values and each method's band.

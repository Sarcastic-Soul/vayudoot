# Submission package

Everything the event asks for, and where it is.

| Required | Where |
| --- | --- |
| Source code, public repo | this repository |
| Deployed link | `vayudoot.onrender.com` |
| Pitch deck, 10–12 slides | [`deck.html`](deck.html) — 12 slides |
| Demo video, 3–5 minutes | [`video-script.md`](video-script.md) — about 4 minutes; recording is yours |
| Brief description, 2–3 lines | [`description.md`](description.md) |
| Where every number comes from | [`sources.md`](sources.md) |

## The deck

Open `deck.html` in a browser. It is one self-contained HTML file with no build
step and no external dependency, matching the rest of the project.

Each slide is a fixed 1280 × 720 (16:9) frame. A small inline script scales it to
the width of the window, so the layout is the same on a laptop and a projector.

**To present:** full-screen the browser and scroll. Each slide is one screen.

**To export a PDF:** print to PDF with background graphics on. The print
stylesheet sets the page to 1280 × 720 px, one slide per page, so paper size and
orientation do not matter. Check the result before submitting.

Screenshots live in `shots/` and are referenced relatively, so the folder moves
as a unit. The ones in use are real captures from a running instance:

| File | What it shows |
| --- | --- |
| `ops-satellite.png` | Operations view with NASA GIBS true-colour, aerosol and fire layers |
| `imagery.png` | Gemini's reading of the VIIRS picture of one hotspot |
| `exposure.png` | People within 10 km, from GeoNames |
| `alert-review.png`, `alert-decision.png`, `alert-sent.png` | Alert drafted, the confirm step, the sandbox envelope |
| `corridor.png` | Lahore–Delhi corridor outlook (a real run: 1 of 6 points answered) |
| `network.png` | A Delhi node reading an Indian and a Pakistan-configured neighbour |

`ops.png`, `detail.png` and `phone.png` are older captures, kept for reference and
no longer used by the deck.

## Deck outline

1. Title
2. The problem — air measured at city scale, breathed at street scale (sourced)
3. Across borders and across BRICS — India–Pakistan, the Highveld, the Amazon (sourced)
4. The insight — a hotspot must not need a citizen to exist
5. What it does, and where Gemini does the work, stage by stage
6. Evidence — every hotspot can be taken apart: satellite reading, exposure, three rules
7. Alert — from a hotspot to the board, once a person confirms; sandboxed
8. Forecast — corridor outlooks with the work shown; never official
9. Interoperability — Pakistan's Punjab detects, Delhi forecasts, no shared weights
10. Depth and reach — 36 states and UTs, 7 corridors, 2 countries, all as data
11. Deployability — one container, free tier, no card, model fallback
12. Impact, and what is honestly not claimed

## Mapping to the judging weights

| Weight | Criterion | Slides |
| --- | --- | --- |
| 25% | AI / Technical execution | 5, 6, 7, 8 |
| 20% | Problem–solution fit | 2, 3, 4 |
| 20% | Depth & reach | 3, 9, 10 |
| 20% | Deployability & scalability | 9, 11 |
| 15% | Impact potential | 2, 3, 12 |

## Video

`video-script.md` runs about 4 minutes in seven shots: the problem (0:00),
the operations view with satellite layers (0:30), taking a hotspot apart
(1:00), the alert and its confirm step (1:40), the citizen path (2:10), the
cross-border feed and the Lahore–Delhi corridor (2:40), and the close (3:35). It
includes the commands that start the three demo nodes.

## Not yet in the pitch

These are marked in the files as `[TODO pending: ...]` comments and must not be
claimed until they are merged and working: South Africa and Brazil nodes,
forecast accuracy measurement, sharing the forecaster between nodes, voice
reports, and BigQuery export.

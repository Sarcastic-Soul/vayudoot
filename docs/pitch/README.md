# Submission package

Everything the event asks for, and where it is.

| Required | Where |
| --- | --- |
| Source code, public repo | this repository |
| Deployed link | `vayudoot.onrender.com` |
| Pitch deck, 10–12 slides | [`deck.html`](deck.html) — 12 slides |
| Demo video, 3–5 minutes | [`video-script.md`](video-script.md) — script; recording is yours |
| Brief description, 2–3 lines | [`description.md`](description.md) |

## The deck

Open `deck.html` in a browser. It is one self-contained HTML file with no build
step and no dependency, matching the rest of the project.

**To present:** full-screen the browser and scroll. Each slide is one screen.

**To export a PDF:** print to PDF at A4 or Letter, **landscape**, with
background graphics on. The print stylesheet puts one slide per page. Check the
result before submitting — the screenshots are the part most likely to spill.

Screenshots live in `shots/` and are referenced relatively, so the folder moves
as a unit. Regenerate them from a running instance if the interface changes.

## Deck outline

1. Title
2. The problem — city-scale monitoring, street-scale exposure
3. The insight — a hotspot must not need a citizen to exist
4. What it does, with the operations view
5. Where Google AI does the work, stage by stage
6. Safety — a public map is a public claim about a place
7. Evidence — every hotspot can be taken apart
8. Forecasting, with real output from a live run
9. Federation — Punjab detects, Delhi forecasts
10. Depth and reach across India
11. Deployability — one container, free tier, no card
12. Impact, and what is honestly not claimed

## Mapping to the judging weights

| Weight | Criterion | Slides |
| --- | --- | --- |
| 25% | AI / Technical execution | 5, 7, 8 |
| 20% | Problem–solution fit | 2, 3, 4 |
| 20% | Depth & reach across India | 9, 10 |
| 20% | Deployability & scalability | 10, 11 |
| 15% | Impact potential | 2, 12 |

Slide 6 serves no single criterion and earns its place anyway: it is the
difference between a prototype somebody would pilot and one nobody could.

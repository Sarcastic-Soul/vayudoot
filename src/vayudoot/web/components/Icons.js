/* The icon set, in one file, so a stroke weight or a viewBox is changed once.
 *
 * Every icon is a 24×24 stroked outline on the same grid, drawn with no fill:
 * colour, weight and size are decided by the control around it in CSS, which
 * is what keeps a 15px node tick and a 22px nav glyph looking like one family.
 * Every icon is decorative — the control around it carries the label. */

import { html } from "../lib/html.js";

const icon = (body) => () => html`<svg viewBox="0 0 24 24" aria-hidden="true">${body}</svg>`;

/* ── navigation ─────────────────────────────────────────────────────── */

export const CameraIcon = icon(html`
  <path d="M4 8h3l2-2h6l2 2h3v11H4z" /><circle cx="12" cy="13" r="3.2" />`);

export const ListIcon = icon(html`<path d="M4 6h16M4 12h16M4 18h10" />`);

export const PinIcon = icon(html`
  <path d="M12 21s7-6.1 7-11a7 7 0 1 0-14 0c0 4.9 7 11 7 11z" /><circle cx="12" cy="10" r="2.6" />`);

/* ── theme ──────────────────────────────────────────────────────────── */

export const SunIcon = icon(html`
  <circle cx="12" cy="12" r="4.2" />
  <path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.9 4.9l1.5 1.5m11.2 11.2 1.5 1.5M19.1 4.9l-1.5 1.5M6.4 17.6l-1.5 1.5" />`);

export const SystemIcon = icon(html`
  <rect x="3" y="4.5" width="18" height="12" rx="1.6" /><path d="M8 20h8" />`);

export const MoonIcon = icon(html`<path d="M20 13.5A8 8 0 0 1 10.5 4a8 8 0 1 0 9.5 9.5z" />`);

/* ── chrome ─────────────────────────────────────────────────────────── */

export const ChevronIcon = icon(html`<path d="M14.5 7.5 10 12l4.5 4.5" />`);

export const ExpandIcon = icon(html`<path d="M9 4H4v5M15 4h5v5M15 20h5v-5M9 20H4v-5" />`);

export const BackIcon = icon(html`<path d="M19 12H5m0 0 6-6m-6 6 6 6" />`);

/* Vayudoot is the wind's messenger: three strokes being carried somewhere,
   rather than a leaf or a shield. Drawn open-ended so it reads as movement. */
export const WindMark = icon(html`
  <path d="M3 8.5h9.5a3 3 0 1 0-3-3" />
  <path d="M3 12.5h13a3 3 0 1 1-3 3" />
  <path d="M3 16.5h6" />`);

/* ── stage state ────────────────────────────────────────────────────── */

export const CheckIcon = icon(html`<path d="M5 12.5 10 17.5 19 7" />`);

export const CrossIcon = icon(html`<path d="M7 7l10 10M17 7 7 17" />`);

/* ── status ─────────────────────────────────────────────────────────── */

/* Awaiting confirmation: a hand, not a warning triangle. Nothing has gone
   wrong; the system is deliberately waiting for a person. */
export const HandIcon = icon(html`
  <path d="M9 11V5.5a1.5 1.5 0 0 1 3 0V11m0 0V4.5a1.5 1.5 0 0 1 3 0V11m0 0V6.5a1.5 1.5 0 0 1 3 0V15a6 6 0 0 1-6 6h-1a6 6 0 0 1-5.2-3L4 14.5a1.6 1.6 0 0 1 2.6-1.9L9 15.5V11z" />`);

export const FiledIcon = icon(html`
  <path d="M5 4.5h9l5 5V19a.5.5 0 0 1-.5.5h-13A.5.5 0 0 1 5 19z" />
  <path d="M14 4.5V10h5M9 14.5l2.2 2.2 4-4.2" />`);

export const EscalateIcon = icon(html`
  <path d="M12 19V6m0 0-5 5m5-5 5 5" /><path d="M5 4h14" />`);

export const HeldIcon = icon(html`
  <circle cx="12" cy="12" r="8.2" /><path d="M12 8v4.6l3 1.8" />`);

export const FailedIcon = icon(html`
  <circle cx="12" cy="12" r="8.2" /><path d="M12 7.5v5.5M12 16.3v.2" />`);

/* Acknowledged: a reply arriving. Deliberately an inbound arrow rather than a
   tick — a receipt is not a remedy, and a tick would say the case was done. */
export const ReplyIcon = icon(html`
  <path d="M9.5 6.5 4.5 11.5l5 5" />
  <path d="M4.5 11.5h9a6 6 0 0 1 6 6v1" />`);

/* Resolved: the one tick in the status set, in a closed ring, because this is
   the only ending the whole system is actually aiming at. */
export const ResolvedIcon = icon(html`
  <circle cx="12" cy="12" r="8.2" /><path d="M8.3 12.3 11 15l4.8-5.2" />`);

/* Withdrawn: taken back. An arrow returning the way it came, not a cross —
   nothing went wrong here, the citizen changed their mind. */
export const WithdrawIcon = icon(html`
  <path d="M20 12.5a8 8 0 1 1-2.6-5.9" />
  <path d="M20.4 3.8v4.6h-4.6" />`);

export const SendIcon = icon(html`
  <path d="M20.5 3.5 10 14M20.5 3.5l-6.6 17-3.9-6.5L3.5 10z" />`);

export const LockIcon = icon(html`
  <rect x="4.5" y="10.5" width="15" height="9.5" rx="2" />
  <path d="M8.5 10.5V7.5a3.5 3.5 0 0 1 7 0v3" />`);

/* ── empty states ───────────────────────────────────────────────────── */

export const InboxIcon = icon(html`
  <path d="M3.5 13.5 6 5h12l2.5 8.5V19a.5.5 0 0 1-.5.5H4a.5.5 0 0 1-.5-.5z" />
  <path d="M3.5 13.5H9a3 3 0 0 0 6 0h5.5" />`);

export const ImagePlusIcon = icon(html`
  <path d="M20.5 12.5V6a1.5 1.5 0 0 0-1.5-1.5H5A1.5 1.5 0 0 0 3.5 6v11A1.5 1.5 0 0 0 5 18.5h8" />
  <path d="m3.5 15 4.2-4.2a1.5 1.5 0 0 1 2.1 0l4.2 4.2" />
  <circle cx="15" cy="9" r="1.4" />
  <path d="M18 16.5h5M20.5 14v5" />`);

/* ── patterns and paperwork ─────────────────────────────────────────── */

/* A repeat pattern: the map circle it is drawn as, with the reports inside
   it. Not a bar chart and not a stack of documents — the thing that makes a
   cluster a cluster is that several reports fall inside one radius. */
export const PatternIcon = icon(html`
  <circle cx="12" cy="12" r="8.4" />
  <circle cx="9.4" cy="10.2" r="1.2" />
  <circle cx="14.6" cy="9.6" r="1.2" />
  <circle cx="11.8" cy="14.8" r="1.2" />`);

/* An RTI application: a form with a question on it. The complaint asks an
   authority to act; this asks it what is written in a file, and the question
   mark is the whole difference between the two documents. */
export const AskIcon = icon(html`
  <path d="M6 3.5h8l4 4V20a.5.5 0 0 1-.5.5H6.5A.5.5 0 0 1 6 20z" />
  <path d="M14 3.5V8h4" />
  <path d="M10.3 12.3a1.75 1.75 0 1 1 2.35 1.65c-.5.19-.8.67-.8 1.2v.35" />
  <path d="M11.85 17.6v.2" />`);

export const CopyIcon = icon(html`
  <rect x="9" y="9" width="11" height="11.5" rx="1.6" />
  <path d="M15.5 5.5A1.5 1.5 0 0 0 14 4H5.5A1.5 1.5 0 0 0 4 5.5V14a1.5 1.5 0 0 0 1.5 1.5" />`);

/* ── hotspots: the sources a detection is built from ──────────────────── */

/* The operations view. Concentric rings around a place, not a pin in one:
   a hotspot is an area by construction, and the nav glyph should not be the
   first thing in the interface to imply otherwise. */
export const HotspotIcon = icon(html`
  <circle cx="12" cy="12" r="2.4" />
  <circle cx="12" cy="12" r="6" />
  <circle cx="12" cy="12" r="9.6" />`);

/* A satellite: an instrument in orbit, with its panels out. Independent
   evidence, and the glyph should read as machinery rather than as a person. */
export const SatelliteIcon = icon(html`
  <rect x="9.2" y="9.2" width="5.6" height="5.6" rx="1" transform="rotate(45 12 12)" />
  <path d="M7.5 7.5 4 4M16.5 16.5 20 20M16.5 7.5 20 4M7.5 16.5 4 20" />`);

/* A ground station: a fixed mast taking a reading. */
export const StationIcon = icon(html`
  <path d="M12 20V9" /><circle cx="12" cy="6.4" r="2.4" />
  <path d="M7 20h10M8.2 13.5 12 9l3.8 4.5" />`);

/* A citizen sensor: a small device reporting a number. Deliberately drawn
   like a gadget rather than like the station above — it is not independent
   evidence and the two must not read as the same class of thing. */
export const SensorIcon = icon(html`
  <rect x="5.5" y="4.5" width="13" height="15" rx="2" />
  <path d="M8.5 15.5h7M8.5 8h7v4h-7z" />`);

/* Uncorroborated: an open ring with a break in it. Not a warning triangle —
   nothing has gone wrong, a piece of the evidence is simply missing. */
export const UnverifiedIcon = icon(html`
  <path d="M12 3.8a8.2 8.2 0 1 1-5.8 14" />
  <path d="M4.4 14.6A8.2 8.2 0 0 1 4.2 11" />
  <path d="M12 8.2v4.4M12 16v.2" />`);

export const SourceIcon = { satellite: SatelliteIcon, ground_station: StationIcon,
  citizen_sensor: SensorIcon, citizen_report: CameraIcon };

/* ── forecasting and the network ──────────────────────────────────────── */

/* The forecast view: a line that is solid up to now and broken after it. The
   break is the point — what is to the right of it has not happened, and the
   glyph should not draw it with the same confidence as what has. */
export const ForecastIcon = icon(html`
  <path d="M3 17.5 7.5 13l3.5 2.5 3.5-5" />
  <path d="M16.2 8.2 17.4 6.6M19 4.6l1.2-1.5" />
  <path d="M3 21h18" />`);

/* Model-derived: a four-point spark. It marks everything predictive, so a
   reader learns to see it as "this is a model's reasoning" before reading a
   word. Deliberately nothing like a seal, a shield or a crest. */
export const ModelIcon = icon(html`
  <path d="M12 3.5c.6 4.3 2.2 5.9 6.5 6.5-4.3.6-5.9 2.2-6.5 6.5-.6-4.3-2.2-5.9-6.5-6.5 4.3-.6 5.9-2.2 6.5-6.5z" />
  <path d="M18.5 15.5v4M16.5 17.5h4" />`);

/* A network of nodes: three instances, each linked to the others. No centre,
   because a federation of state instances has none. */
export const NetworkIcon = icon(html`
  <circle cx="12" cy="5.5" r="2.3" /><circle cx="5.5" cy="17.5" r="2.3" />
  <circle cx="18.5" cy="17.5" r="2.3" />
  <path d="M10.9 7.5 6.6 15.5M13.1 7.5l4.3 8M7.8 17.5h8.4" />`);

/* A published feed: a file with lines going out of it. */
export const FeedIcon = icon(html`
  <path d="M6 3.5h8l4 4V20a.5.5 0 0 1-.5.5H6.5A.5.5 0 0 1 6 20z" />
  <path d="M14 3.5V8h4M9 12.5h6M9 15.5h6M9 18h3.5" />`);

/* A globe, for the GIS format that every mapping tool opens. */
export const GlobeIcon = icon(html`
  <circle cx="12" cy="12" r="8.5" />
  <path d="M3.5 12h17M12 3.5c2.4 2.4 3.6 5.2 3.6 8.5S14.4 18.1 12 20.5M12 3.5C9.6 5.9 8.4 8.7 8.4 12s1.2 6.1 3.6 8.5" />`);

/* A border being crossed: a dashed line, and an arrow going over it. */
export const BorderIcon = icon(html`
  <path d="M12 3v2.5M12 9v2.5M12 15v2.5M12 20.5V21" />
  <path d="M4 12.5c2.5-3 5.5-4 9-3.5 2.4.4 4.3 1.6 6 3.5m0 0-.5-3.6m.5 3.6-3.6.3" />`);

export const RetryIcon = icon(html`
  <path d="M4 12.5a8 8 0 1 0 2.6-5.9" />
  <path d="M3.6 3.8v4.6h4.6" />`);

export const OutIcon = icon(html`
  <path d="M14 4.5h5.5V10M19.5 4.5 11 13" />
  <path d="M18 14v5a.5.5 0 0 1-.5.5h-12A.5.5 0 0 1 5 19V7a.5.5 0 0 1 .5-.5H10" />`);

/* ── the hotspot's actions ──────────────────────────────────────────── */

/* Map layers: three sheets stacked. The satellite control on every hotspot
   map, so the glyph is the familiar one rather than a clever one. */
export const LayersIcon = icon(html`
  <path d="M12 4 3.5 8.5 12 13l8.5-4.5z" />
  <path d="m3.5 12.5 8.5 4.5 8.5-4.5" />
  <path d="m3.5 16.5 8.5 4.5 8.5-4.5" />`);

/* People within reach: two heads, one behind the other. A count of people,
   never a face, so the glyph is deliberately generic. */
export const PeopleIcon = icon(html`
  <circle cx="9" cy="8.5" r="3" />
  <path d="M3.5 19.5c.6-3.4 2.7-5.2 5.5-5.2s4.9 1.8 5.5 5.2" />
  <path d="M15.2 5.8a3 3 0 0 1 0 5.4M17 14.6c1.9.6 3.1 2.2 3.5 4.9" />`);

/* An alert to an authority: an envelope with a mark on it. A letter, not a
   siren — this tells an office something, it does not sound an alarm. */
export const AlertMailIcon = icon(html`
  <rect x="3.5" y="6" width="17" height="12.5" rx="1.5" />
  <path d="m4 7 8 6 8-6" />
  <circle cx="19" cy="5.5" r="2.6" />`);

/* Looking at a picture: an eye. For the imagery reading, which is someone —
   a model — looking, not something measuring. */
export const EyeIcon = icon(html`
  <path d="M2.8 12S6.2 5.8 12 5.8 21.2 12 21.2 12 17.8 18.2 12 18.2 2.8 12 2.8 12z" />
  <circle cx="12" cy="12" r="2.8" />`);

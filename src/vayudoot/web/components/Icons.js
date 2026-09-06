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

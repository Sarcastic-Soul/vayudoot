/* The icon set, in one file, so a stroke weight or a viewBox is changed once.
 * Every icon is decorative: the control around it carries the label. */

import { html } from "../lib/html.js";

const icon = (body) => () => html`<svg viewBox="0 0 24 24" aria-hidden="true">${body}</svg>`;

export const CameraIcon = icon(html`
  <path d="M4 8h3l2-2h6l2 2h3v11H4z" /><circle cx="12" cy="13" r="3.2" />`);

export const ListIcon = icon(html`<path d="M4 6h16M4 12h16M4 18h10" />`);

export const PinIcon = icon(html`
  <path d="M12 21s7-6.1 7-11a7 7 0 1 0-14 0c0 4.9 7 11 7 11z" /><circle cx="12" cy="10" r="2.6" />`);

export const SunIcon = icon(html`
  <circle cx="12" cy="12" r="4.2" />
  <path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.9 4.9l1.5 1.5m11.2 11.2 1.5 1.5M19.1 4.9l-1.5 1.5M6.4 17.6l-1.5 1.5" />`);

export const SystemIcon = icon(html`
  <rect x="3" y="4.5" width="18" height="12" rx="1.6" /><path d="M8 20h8" />`);

export const MoonIcon = icon(html`<path d="M20 13.5A8 8 0 0 1 10.5 4a8 8 0 1 0 9.5 9.5z" />`);

export const ChevronIcon = icon(html`<path d="M14.5 7.5 10 12l4.5 4.5" />`);

export const ExpandIcon = icon(html`<path d="M9 4H4v5M15 4h5v5M15 20h5v-5M9 20H4v-5" />`);

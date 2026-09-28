/* A country's flag, drawn, beside its ISO code.
 *
 * Emoji flags are a font feature, and most desktop systems do not have it:
 * Windows draws "🇿🇦" as the letters Z A, and so does a Linux box without an
 * emoji font. The countries this network actually runs nodes in — India,
 * South Africa, Brazil, and Pakistan for the cross-border corridor — are
 * therefore drawn as small inline SVGs that render the same everywhere. Any
 * other code falls back to the emoji, and the ISO code is always shown beside
 * the picture: a flag is never the only label.
 *
 * Simplified to what reads at 20 pixels. No clip paths or gradients, because a
 * clip path defined inside a hidden view does not paint in every browser, and
 * several views mount while hidden.
 */

import { html } from "../lib/html.js";
import { flagOf, countryName } from "../lib/format.js";

/* Each is drawn in a 30 × 20 box. Functions, so every flag on a page is its own
   vnode rather than one shared between places. */
const DRAWN = {
  IN: () => html`
    <rect width="30" height="20" fill="#fff" />
    <rect width="30" height="6.67" fill="#FF9933" />
    <rect y="13.33" width="30" height="6.67" fill="#138808" />
    <circle cx="15" cy="10" r="2.6" fill="none" stroke="#000080" stroke-width="0.7" />
    <circle cx="15" cy="10" r="0.6" fill="#000080" />`,
  ZA: () => html`
    <rect width="30" height="10" fill="#E03C31" />
    <rect y="10" width="30" height="10" fill="#001489" />
    <path d="M0 0 L15 10 L30 10 M0 20 L15 10" fill="none" stroke="#fff" stroke-width="6.6" />
    <path d="M0 0 L15 10 L0 20 Z" fill="#FFB81C" />
    <path d="M0 3.3 L9.9 10 L0 16.7 Z" fill="#000" />
    <path d="M0 0 L15 10 L30 10 M0 20 L15 10" fill="none" stroke="#007749" stroke-width="4" />`,
  BR: () => html`
    <rect width="30" height="20" fill="#009C3B" />
    <path d="M15 2 L27.5 10 L15 18 L2.5 10 Z" fill="#FFDF00" />
    <circle cx="15" cy="10" r="4.4" fill="#002776" />
    <path d="M10.8 8.9 Q15 7.6 19.3 10.6" fill="none" stroke="#fff" stroke-width="0.9" />`,
  PK: () => html`
    <rect width="30" height="20" fill="#01411C" />
    <rect width="7.5" height="20" fill="#fff" />
    <circle cx="19.5" cy="10" r="5" fill="#fff" />
    <circle cx="21" cy="8.8" r="4.4" fill="#01411C" />
    <path d="M22.9 7.1 l0.55 1.5 1.6 0 -1.3 1 0.5 1.5 -1.35 -0.9 -1.3 0.9 0.5 -1.5 -1.3 -1 1.6 0z"
          fill="#fff" />`,
};

/* The picture alone, for places that already say the country in words. */
export function FlagMark({ code, size = 20 }) {
  const iso = String(code || "").toUpperCase();
  const drawn = DRAWN[iso];
  if (drawn) {
    return html`
      <svg class="flag-svg" viewBox="0 0 30 20" width=${size} height=${(size * 2) / 3}
           aria-hidden="true" focusable="false">${drawn()}</svg>`;
  }
  const emoji = flagOf(iso);
  return emoji ? html`<span class="flag-emoji" aria-hidden="true">${emoji}</span>` : null;
}

/* Picture and code, the default. `name` adds the country's name in words. */
export function Flag({ code, name = false, size = 20 }) {
  const iso = String(code || "").toUpperCase();
  return html`
    <span class="flag" title=${countryName(iso) || null}>
      <${FlagMark} code=${iso} size=${size} />
      <span class="flag-code">${iso || "—"}</span>
      ${name && iso && html`<span class="flag-name">${countryName(iso)}</span>`}
    </span>`;
}

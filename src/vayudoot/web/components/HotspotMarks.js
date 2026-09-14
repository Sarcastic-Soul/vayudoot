/* The three marks every hotspot carries, in one file so they cannot drift.
 *
 * Severity, confidence and corroboration are three different statements about
 * a place, and the whole design problem is keeping them apart:
 *
 * - **Severity** is how bad the thing is. It is a band, drawn in a ramp of
 *   colour, and it is always accompanied by its word — this is read outdoors
 *   in glare and by people who do not separate amber from red.
 * - **Confidence** is how sure the system is the thing is there at all. It is
 *   a percentage with a meter, in neutral ink, deliberately on no ramp. A
 *   single ramp carrying both would say a certain small fire is a catastrophe,
 *   which is the exact overclaim `hotspots.signal_from_case` exists to stop.
 * - **Corroboration** is whether anything outside the public agrees. It is
 *   never a colour or an icon alone, and it never appears far from the
 *   confidence it qualifies, because a capped number shown without the cap is
 *   the one presentation hard constraint 7 forbids.
 */

import { html } from "../lib/html.js";
import { percent, corroborationOf } from "../lib/format.js";
import { UnverifiedIcon, CheckIcon } from "./Icons.js";

export function SeverityChip({ severity }) {
  return html`
    <span class="sev" data-severity=${severity}>
      <span class="sev-dot" aria-hidden="true"></span>${severity}
    </span>`;
}

/* The meter is decorative — the number beside it is the fact — so it is
 * hidden from assistive technology rather than given a duplicate label. */
export function ConfidenceMeter({ value, capped }) {
  const pct = Math.round((value || 0) * 100);
  return html`
    <span class=${`conf${capped ? " is-capped" : ""}`}>
      <span class="conf-num tnum">${percent(value)}</span>
      <span class="meter" aria-hidden="true">
        <span class="meter-fill" style=${`width:${pct}%`}></span>
      </span>
    </span>`;
}

/* The two figures side by side, each under its own word. The labels are not
 * decoration: "72%" beside "High" with nothing naming them is exactly how two
 * different measures get read as one. */
export function Figures({ hotspot, size = "row" }) {
  return html`
    <span class=${`figures is-${size}`}>
      <span class="figure">
        <span class="figure-label">Severity</span>
        <${SeverityChip} severity=${hotspot.severity} />
      </span>
      <span class="figure">
        <span class="figure-label">Confidence</span>
        <${ConfidenceMeter} value=${hotspot.confidence} capped=${!hotspot.corroborated} />
      </span>
    </span>`;
}

/* The corroboration state, spelled out. `full` adds the sentence that says
 * what the flag costs; the badge alone is for a dense list row, and even there
 * it says "not independently corroborated" in words rather than relying on the
 * colour it is drawn in. */
export function CorroborationBadge({ hotspot, full = false }) {
  const state = corroborationOf(hotspot);
  const Icon = state.ok ? CheckIcon : UnverifiedIcon;
  return html`
    <span class=${`corr${state.ok ? " is-ok" : " is-uncorroborated"}${full ? " is-full" : ""}`}>
      <${Icon} />
      <span class="corr-body">
        <span class="corr-label">${state.label}</span>
        ${full && html`<span class="corr-detail">${state.detail}</span>`}
      </span>
    </span>`;
}

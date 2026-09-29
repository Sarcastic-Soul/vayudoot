/* Who lives close enough to a hotspot to be breathing it.
 *
 * A number of people is what turns a circle on a map into a priority, which is
 * why it is shown — and a number of people is also the easiest thing on this
 * page to overstate, which is why it is shown the way it is. The server's
 * figure is a coarse gazetteer count: the populations of places over a size
 * floor whose centre lies within a radius. Villages under the floor are
 * missed, and a city is counted whole when its centre is in reach. So:
 *
 * - it is always "about", rounded, and never written to the unit;
 * - it always carries its radius, because "1.6M people" with no distance is a
 *   different and false claim;
 * - the server's `basis` sentence is shown verbatim, behind a "How is this
 *   counted?" disclosure, with "a coarse estimate" said on the card itself;
 * - towns are places, never facilities — hard constraint 7 — and are listed
 *   because "Ludhiana" is what makes the number make sense.
 *
 * A null exposure means nothing large is in reach according to the gazetteer.
 * That is said as exactly that, and never as "nobody lives here".
 */

import { html } from "../lib/html.js";
import { exposureLine, peopleShort, plural } from "../lib/format.js";
import { PeopleIcon } from "./Icons.js";

/* The one-line version, for a hotspot card. Says nothing when there is
   nothing: a card is not the place to explain an absence. */
export function ExposureChip({ exposure }) {
  if (!exposure) return null;
  return html`
    <span class="exposure-chip" title="Coarse estimate from a gazetteer of towns">
      <${PeopleIcon} /><span class="tnum">${exposureLine(exposure)}</span>
    </span>`;
}

export function ExposurePanel({ exposure }) {
  if (!exposure) {
    return html`
      <section class="exposure-card is-empty" aria-labelledby="exposure-heading">
        <div class="alert-card-head">
          <span class="alert-glyph is-muted" aria-hidden="true"><${PeopleIcon} /></span>
          <div>
            <p class="eyebrow">Who is in reach</p>
            <h3 id="exposure-heading">No large town in reach</h3>
          </div>
        </div>
        <p class="alert-why">Not the same as nobody here: villages and farms are not counted.</p>
        <details class="why">
          <summary>How is this counted?</summary>
          <p>From a gazetteer of towns of 15,000 people or more; none has its centre within
            reach of this hotspot.</p>
        </details>
      </section>`;
  }
  const towns = exposure.towns || [];
  return html`
    <section class="exposure-card" aria-labelledby="exposure-heading">
      <div class="alert-card-head">
        <span class="alert-glyph" aria-hidden="true"><${PeopleIcon} /></span>
        <div>
          <p class="eyebrow">Who is in reach · coarse estimate</p>
          <h3 id="exposure-heading" class="exposure-figure"
              title=${`About ${exposure.population.toLocaleString("en-IN")} people`}>
            <span class="tnum">~${peopleShort(exposure.population)}</span>
            <span class="exposure-unit">people within ${Math.round(exposure.radius_km)} km</span>
          </h3>
        </div>
      </div>
      ${towns.length > 0 && html`
        <ul class="exposure-towns" aria-label="Largest places counted">
          ${towns.map((town) => html`<li key=${town}>${town}</li>`)}
          ${(exposure.settlement_count || 0) > towns.length && html`
            <li class="is-more tnum">
              +${plural(exposure.settlement_count - towns.length, "more place")}</li>`}
        </ul>`}
      ${exposure.basis && html`
        <details class="why">
          <summary>How is this counted?</summary>
          <p class="exposure-basis">${exposure.basis}</p>
        </details>`}
    </section>`;
}

/* One hotspot: what it is, and — the point of the page — what it is built from.
 *
 * A number on a map is an assertion. The reason this view exists is so that
 * every hotspot can be taken apart into the individual observations underneath
 * it, each named by its source and its time, so a reader can decide for
 * themselves whether the confidence above is earned. That is also the only
 * honest way to publish a capped confidence: show the cap, then show exactly
 * what is missing.
 *
 * **The signals are a list, not pins.** Each one has coordinates and it would
 * be easy to plot them, and plotting them would undo the constraint the whole
 * map obeys: the hotspot is published as an area precisely so that it cannot be
 * read as an accusation against one address, and three dots inside the circle
 * would hand back the address the radius was there to withhold. Hard constraint
 * 7. Contributing cases are linked instead, which is where a reader with
 * standing to see the detail already goes.
 *
 * The page reads top to bottom as: what and where (the kind and the nearest
 * town are the headline; the id is secondary), the facts as tiles with the
 * corroboration band under them, then the map beside who is in reach and the
 * evidence, then the two things an operator does next — the alert to the
 * authority, which ends in a decision and so takes the larger column, and a
 * look at the satellite picture.
 */

import { html, Fragment } from "../lib/html.js";
import { navigate } from "../lib/router.js";
import { useHotspot } from "../lib/store.js";
import {
  words, onDate, atTime, shortWhen, plural, percent, radiusLabel, spanLabel,
  sourceBreakdown, sourceLabel, SOURCE_BLURB, corroborationOf, countedSources,
} from "../lib/format.js";
import { HotspotsMap } from "./HotspotsMap.js";
import { SeverityChip, ConfidenceMeter, CorroborationBadge, hotspotTitle } from "./HotspotMarks.js";
import { CaseListSkeleton } from "./Skeletons.js";
import { ExposurePanel } from "./Exposure.js";
import { HotspotAlert } from "./HotspotAlert.js";
import { ImageryCheck } from "./ImageryCheck.js";
import { BackIcon, HotspotIcon, SourceIcon } from "./Icons.js";

function SignalRow({ signal }) {
  const Icon = SourceIcon[signal.source];
  const at = Date.parse(signal.observed_at);
  return html`
    <li class=${`signal${signal.source === "satellite" || signal.source === "ground_station"
      ? " is-independent" : ""}`}>
      <span class="signal-mark" aria-hidden="true">${Icon && html`<${Icon} />`}</span>
      <span class="signal-body">
        <span class="signal-head">
          <span class="signal-source">${sourceLabel(signal.source)}</span>
          <span class="signal-when">
            ${Number.isNaN(at) ? "" : `${onDate(signal.observed_at)}, ${atTime(at)}`}
          </span>
        </span>
        <span class="signal-summary">${signal.summary || words(signal.pollution_type)}</span>
        <span class="signal-figures">
          <span title="How sure the source is the observation is real">
            <span class="figure-label">Certainty</span>
            <span class="tnum">${percent(signal.strength)}</span></span>
          <span title="How large the observed thing is">
            <span class="figure-label">Size</span>
            <span class="tnum">${percent(signal.magnitude)}</span></span>
          ${signal.pollution_type !== "unclear" &&
            html`<span class="signal-kind">${words(signal.pollution_type)}</span>`}
        </span>
      </span>
    </li>`;
}

/* The facts as tiles. Severity and confidence each keep their own label —
   the two measures side by side and never merged — and the rest is the
   detection's extent in space and time. */
function Facts({ hotspot }) {
  return html`
    <dl class="hs-facts">
      <div data-severity=${hotspot.severity}>
        <dt>Severity</dt><dd><${SeverityChip} severity=${hotspot.severity} /></dd>
      </div>
      <div>
        <dt>Confidence</dt>
        <dd><${ConfidenceMeter} value=${hotspot.confidence} capped=${!hotspot.corroborated} /></dd>
      </div>
      <div><dt>Area</dt><dd class="tnum">${radiusLabel(hotspot.radius_km)}<small> radius</small></dd></div>
      <div><dt>Signals</dt><dd class="tnum">${hotspot.signal_count}</dd></div>
      <div><dt>Running for</dt><dd>${spanLabel(hotspot.span_days)}</dd></div>
      <div title=${`First signal ${onDate(hotspot.first_seen_at)}, `
        + `latest ${onDate(hotspot.last_seen_at)}`}>
        <dt>Last seen</dt><dd>${shortWhen(hotspot.last_seen_at)}</dd>
      </div>
    </dl>`;
}

export function HotspotView({ hotspotId }) {
  const { data: hotspot, error, gone } = useHotspot(hotspotId);
  const state = hotspot ? corroborationOf(hotspot) : null;

  return html`
    <${Fragment}>
      <div class="case-head">
        <button type="button" class="link back" onClick=${() => navigate("")}>
          <${BackIcon} /> What is happening now
        </button>
        ${!hotspot && html`<h2>${hotspotId}</h2>`}
      </div>

      ${!hotspot && !error && html`<${CaseListSkeleton} />`}

      ${gone && html`
        <div class="empty">
          <${HotspotIcon} />
          <h3>No such hotspot</h3>
          <p>Its signals aged out of the window, or the case behind one was withdrawn. It is
            not a broken link.</p>
          <button type="button" class="primary" onClick=${() => navigate("")}>
            Back to what is happening now
          </button>
        </div>`}

      ${error && !gone && html`
        <p class="note is-bad">Could not load this hotspot: ${error}</p>`}

      ${hotspot && html`
        <${Fragment}>
          <header class="hs-hero" data-severity=${hotspot.severity}>
            <div class="hs-hero-head">
              <p class="hs-hero-id"><${HotspotIcon} />Hotspot <code>${hotspot.hotspot_id}</code></p>
              <h2>${hotspotTitle(hotspot)}</h2>
            </div>
            <${Facts} hotspot=${hotspot} />
            <${CorroborationBadge} hotspot=${hotspot}
              detail=${state.ok
                ? `Backed by ${countedSources(hotspot.source_counts, { independentOnly: true })}.`
                : "Confidence capped until a satellite or station reading agrees."} />
          </header>

          <div class="hs-grid">
            <div class="hs-map">
              <${HotspotsMap} hotspots=${[hotspot]} paneClass="hotspot-map" fitMaxZoom=${14} />
              <p class="map-caption">
                <${HotspotIcon} />
                An area, not an accusation against any address. No party is named.
              </p>
            </div>

            <div class="hs-side">
              <${ExposurePanel} exposure=${hotspot.exposure} />

              <section class="hs-evidence" aria-labelledby="evidence-heading">
                <div class="hs-evidence-head">
                  <h3 id="evidence-heading">Evidence</h3>
                  <ul class="source-tally">
                    ${sourceBreakdown(hotspot.source_counts).map(({ source, count, independent }) => {
                      const Icon = SourceIcon[source];
                      return html`
                        <li key=${source} class=${independent ? "is-independent" : ""}
                            title=${SOURCE_BLURB[source]}>
                          ${Icon && html`<${Icon} />`}
                          <span class="tnum">${plural(count, sourceLabel(source).toLowerCase())}</span>
                        </li>`;
                    })}
                  </ul>
                </div>

                <ul class="signal-list" aria-label="Every signal behind it, oldest first">
                  ${[...hotspot.signals]
                    .sort((a, b) => Date.parse(a.observed_at) - Date.parse(b.observed_at))
                    .map((signal) => html`
                      <${SignalRow} key=${`${signal.source}:${signal.signal_id}`}
                                    signal=${signal} />`)}
                </ul>

                <details class="why">
                  <summary>Certainty vs size</summary>
                  <p>Oldest first. <strong>Certainty</strong> is how sure the source is the
                    observation is real; <strong>size</strong> is how large the observed thing
                    is. A model being certain of what it saw is not the same as what it saw
                    being serious.</p>
                </details>

                ${state && !state.ok && html`
                  <p class="note is-limit">Nothing here came from outside the public.</p>`}

                ${hotspot.case_ids.length > 0 && html`
                  <${Fragment}>
                    <h4 class="section-label">Citizen cases inside it</h4>
                    <ul class="hotspot-cases">
                      ${hotspot.case_ids.map((caseId) => html`
                        <li key=${caseId}>
                          <button type="button" class="link" onClick=${() => navigate(caseId)}>
                            ${caseId}
                          </button>
                        </li>`)}
                    </ul>
                  <//>`}
              </section>
            </div>
          </div>

          <div class="hotspot-act">
            <div class="act-alert"><${HotspotAlert} hotspot=${hotspot} /></div>
            <div class="act-imagery"><${ImageryCheck} hotspot=${hotspot} /></div>
          </div>
        <//>`}
    <//>`;
}

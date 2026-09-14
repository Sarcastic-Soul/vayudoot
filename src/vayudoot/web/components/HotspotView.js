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
 */

import { html, Fragment } from "../lib/html.js";
import { navigate } from "../lib/router.js";
import { useHotspot } from "../lib/store.js";
import {
  words, onDate, atTime, plural, percent, radiusLabel, spanLabel,
  sourceBreakdown, sourceLabel, SOURCE_BLURB, corroborationOf,
} from "../lib/format.js";
import { HotspotsMap } from "./HotspotsMap.js";
import { Figures, CorroborationBadge } from "./HotspotMarks.js";
import { CaseListSkeleton } from "./Skeletons.js";
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
          <span><span class="figure-label">Certainty</span>
            <span class="tnum">${percent(signal.strength)}</span></span>
          <span><span class="figure-label">Size</span>
            <span class="tnum">${percent(signal.magnitude)}</span></span>
          <span class="signal-kind">${words(signal.pollution_type)}</span>
        </span>
      </span>
    </li>`;
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
        <h2>${hotspotId}</h2>
        ${hotspot && html`
          <p class="hotspot-lead">
            <${HotspotIcon} />
            <span>
              <strong>${words(hotspot.pollution_type)}</strong>, over an area
              ${" "}${radiusLabel(hotspot.radius_km)} across, built from
              ${" "}${plural(hotspot.signal_count, "signal")} across
              ${" "}${spanLabel(hotspot.span_days)}.
            </span>
          </p>`}
      </div>

      ${!hotspot && !error && html`<${CaseListSkeleton} />`}

      ${gone && html`
        <div class="empty">
          <${HotspotIcon} />
          <h3>No such hotspot</h3>
          <p>Detection is worked out from the signals every time it is asked for, so a hotspot
            can stop existing — its signals aged out of the window, or the case behind one of
            them was withdrawn. It is not a broken link.</p>
          <button type="button" class="primary" onClick=${() => navigate("")}>
            Back to what is happening now
          </button>
        </div>`}

      ${error && !gone && html`
        <p class="note is-bad">Could not load this hotspot: ${error}</p>`}

      ${hotspot && html`
        <${Fragment}>
          <div class="hotspot-headline">
            <${Figures} hotspot=${hotspot} size="large" />
            <${CorroborationBadge} hotspot=${hotspot} full=${true} />
          </div>

          <${HotspotsMap} hotspots=${[hotspot]} paneClass="hotspot-map" fitMaxZoom=${14} />
          <p class="map-caption">
            The circle is the hotspot's published extent, not the location of anything inside
            it. Hotspots are drawn as areas and never as points, so that a detection cannot be
            read as an accusation against one address.
          </p>

          <div class="cluster-grid">
            <div class="case-col">
              <h3 class="section-label">What it rests on</h3>
              <ul class="source-tally">
                ${sourceBreakdown(hotspot.source_counts).map(({ source, count, independent }) => {
                  const Icon = SourceIcon[source];
                  return html`
                    <li key=${source} class=${independent ? "is-independent" : ""}>
                      <span class="tally-mark" aria-hidden="true">
                        ${Icon && html`<${Icon} />`}</span>
                      <span class="tally-body">
                        <strong>${plural(count, sourceLabel(source).toLowerCase())}</strong>
                        <span>${SOURCE_BLURB[source]}</span>
                      </span>
                    </li>`;
                })}
              </ul>

              <h3 class="section-label">The detection</h3>
              <dl class="cluster-facts">
                <div><dt>First signal</dt><dd>${onDate(hotspot.first_seen_at)}</dd></div>
                <div><dt>Most recent</dt><dd>${onDate(hotspot.last_seen_at)}</dd></div>
                <div><dt>Running for</dt><dd>${spanLabel(hotspot.span_days)}</dd></div>
                <div><dt>Published extent</dt>
                  <dd>${radiusLabel(hotspot.radius_km)} from the centre</dd></div>
                <div><dt>Severity</dt><dd>${hotspot.severity}, from how large the observations
                  are</dd></div>
                <div><dt>Confidence</dt><dd class="tnum">${percent(hotspot.confidence)}${
                  hotspot.corroborated ? "" : " — capped, see above"}</dd></div>
              </dl>

              ${hotspot.case_ids.length > 0 && html`
                <${Fragment}>
                  <h3 class="section-label">Citizen cases inside it</h3>
                  <ul class="hotspot-cases">
                    ${hotspot.case_ids.map((caseId) => html`
                      <li key=${caseId}>
                        <button type="button" class="link" onClick=${() => navigate(caseId)}>
                          ${caseId}
                        </button>
                      </li>`)}
                  </ul>
                <//>`}

              <p class="note">
                Nothing here names a responsible party, and the system deliberately never will:
                naming one from a photograph is unreliable and seriously harmful when wrong.
                What a hotspot supports is a report of an observation to the authority that
                holds jurisdiction over the area.
              </p>
            </div>

            <div class="case-col">
              <div class="timeline-head">
                <h3 class="section-label">Every signal behind it</h3>
                <p class="timeline-progress tnum">
                  ${plural(hotspot.signals.length, "signal")}</p>
              </div>
              <p class="signal-lead">
                Oldest first. <strong>Certainty</strong> is how sure the source is the
                observation is real; <strong>size</strong> is how large the observed thing is.
                They are separate on purpose — a model being certain of what it saw is not the
                same as what it saw being serious.
              </p>
              <ul class="signal-list">
                ${[...hotspot.signals]
                  .sort((a, b) => Date.parse(a.observed_at) - Date.parse(b.observed_at))
                  .map((signal) => html`
                    <${SignalRow} key=${`${signal.source}:${signal.signal_id}`}
                                  signal=${signal} />`)}
              </ul>
              ${state && !state.ok && html`
                <p class="note is-limit">
                  Nothing in this list came from outside the public. ${state.detail}
                </p>`}
            </div>
          </div>
        <//>`}
    <//>`;
}

/* The operations view: what a city or state air-quality cell opens.
 *
 * This is the front door from v0.3 on, and the swap from the report form is the
 * whole reframe in one change. Through v0.2 the protagonist was a citizen with
 * a grievance and the unit of work was a case; the protagonist here is the cell
 * that has to decide what to look at this morning, and the unit of work is a
 * *place*. `docs/SCOPE.md` under v0.3 records why. Intake did not go anywhere —
 * it is one route along, and a hotspot is still what a complaint gets written
 * about.
 *
 * Map first and large, because the question is "where", and the list beside it
 * because the question after that is "which one first". The two are the same
 * data twice: the map is not an illustration of the list and the list is not a
 * caption for the map, which is also what makes the view usable without a
 * mouse or without sight — everything the circles say is in the rows. Pointing
 * at a row lights its circle, and pointing at a circle lights its row.
 *
 * A strip of four numbers sits above both, and the filter chips narrow the map
 * and the list together. The people figure is the largest single hotspot's
 * reach, never a sum: reaches overlap, and adding them would count one city
 * once per hotspot inside it.
 *
 * The empty state is designed rather than defaulted. It is the state this
 * instance is in most of the time and the one a first-time reader is most
 * likely to hit, and the one sentence it must get right is that an empty map is
 * not clean air.
 */

import { useState } from "../vendor/hooks.mjs";
import { html, Fragment } from "../lib/html.js";
import { navigate } from "../lib/router.js";
import { useHotspots, useAlerts } from "../lib/store.js";
import {
  plural, SOURCE_LABEL, SOURCE_BLURB, latestAlertByHotspot, peopleShort,
} from "../lib/format.js";
import { HotspotsMap, MapLegend } from "./HotspotsMap.js";
import { HotspotCard } from "./HotspotCard.js";
import { HotspotListSkeleton } from "./Skeletons.js";
import {
  CameraIcon, CheckIcon, HotspotIcon, PeopleIcon, SourceIcon, UnverifiedIcon,
} from "./Icons.js";

/* The order signals are introduced in: independent evidence first, because
   that is the half of the list that decides whether anything here is
   corroborated at all. */
const SOURCES = ["satellite", "ground_station", "citizen_report", "citizen_sensor"];

const BANDS = ["severe", "high", "moderate", "low"];

/* Rows shown before "Show all". The list is a scroll panel beside the map on a
   desktop, but on a phone it is the page, and thirty-six rows is a long thumb. */
const FIRST_ROWS = 12;

function SourceKey() {
  return html`
    <ul class="source-key">
      ${SOURCES.map((source) => {
        const Icon = SourceIcon[source];
        return html`
          <li key=${source} title=${SOURCE_BLURB[source]}
              class=${source === "satellite" || source === "ground_station"
                ? "is-independent" : ""}>
            ${Icon && html`<${Icon} />`}<strong>${SOURCE_LABEL[source]}</strong>
          </li>`;
      })}
    </ul>`;
}

/* Nothing detected is a real answer, and it is not the same answer as "the air
   is clean". Saying which is the whole job of this panel. */
function NoHotspots() {
  return html`
    <div class="ops-empty">
      <${HotspotIcon} />
      <h3>Nothing detected right now</h3>
      <p class="ops-empty-lead"><strong>An empty map is not clean air.</strong> It means no
        signal in the window raised a hotspot.</p>
      <details class="why">
        <summary>Why?</summary>
        <p>Most of India is not covered by a ground station, and a place nobody has
          photographed and no satellite has passed over looks exactly like a place with nothing
          wrong. Any one of these sources raises a hotspot on its own; a photograph upgrades a
          thermal anomaly into something a complaint can be written about.</p>
      </details>
      <${SourceKey} />
      <button type="button" class="primary" onClick=${() => navigate("report")}>
        <${CameraIcon} /> Report what you can see
      </button>
    </div>`;
}

function Stat({ value, label, tone = "", children }) {
  return html`
    <div class=${`ops-stat${tone ? ` is-${tone}` : ""}`}>
      <span class="ops-stat-value tnum">${value}</span>
      <span class="ops-stat-label">${label}</span>
      ${children}
    </div>`;
}

function Chip({ on, onClick, count, children, tone = "" }) {
  return html`
    <button type="button" class=${`ops-chip${on ? " is-on" : ""}${tone ? ` ${tone}` : ""}`}
            aria-pressed=${on} onClick=${onClick}>
      ${children}<span class="ops-chip-count tnum">${count}</span>
    </button>`;
}

export function OpsView() {
  const { data, error } = useHotspots();
  const alerts = latestAlertByHotspot(useAlerts());
  const [band, setBand] = useState(null);
  const [evidence, setEvidence] = useState(null);   // null | "ok" | "citizen"
  const [focus, setFocus] = useState(null);
  const [all, setAll] = useState(false);

  const hotspots = data || [];
  const corroborated = hotspots.filter((h) => h.corroborated).length;
  const uncorroborated = hotspots.length - corroborated;
  const serious = hotspots.filter((h) => h.severity === "severe" || h.severity === "high").length;
  const reach = hotspots.reduce((top, h) =>
    (h.exposure && h.exposure.population > (top ? top.population : 0) ? h.exposure : top), null);
  const bandCount = (b) => hotspots.filter((h) => h.severity === b).length;

  const shown = hotspots.filter((h) => (!band || h.severity === band)
    && (!evidence || (evidence === "ok") === Boolean(h.corroborated)));
  const rows = all ? shown : shown.slice(0, FIRST_ROWS);

  /* One sentence, announced when it changes, carrying the two numbers that
     decide how the list should be read. The strip shows them; this says them. */
  const status = !data
    ? "Loading the hotspots."
    : hotspots.length === 0
      ? "No hotspots currently detected."
      : `${plural(hotspots.length, "hotspot")} detected. `
        + (uncorroborated === 0
          ? "All are independently corroborated."
          : `${uncorroborated} of them rest on citizen reports alone and are not `
            + "independently corroborated.");

  return html`
    <${Fragment}>
      <header class="page-head ops-head">
        <h2>What is happening now</h2>
        <p>Live pollution hotspots from photos, satellites and ground stations.</p>
      </header>

      <p class="visually-hidden" role="status">${status}</p>

      ${error && html`
        <p class="note is-bad">Could not reach the detection layer: ${error}
          ${data && data.length > 0 && " What is on screen is the last good reading."}</p>`}

      ${data && hotspots.length > 0 && html`
        <div class="ops-stats">
          <${Stat} value=${hotspots.length} label="Hotspots">
            <${HotspotIcon} />
          <//>
          <${Stat} value=${serious} label="Severe or high" tone=${serious ? "severe" : ""}>
            <span class="ops-stat-bar" aria-hidden="true">
              ${BANDS.map((b) => bandCount(b) > 0 && html`
                <span key=${b} data-severity=${b}
                      style=${`flex:${bandCount(b)}`}></span>`)}
            </span>
          <//>
          <${Stat} value=${html`${corroborated}<small>/${hotspots.length}</small>`}
                   label="Corroborated" tone=${uncorroborated ? "attention" : "ok"}>
            ${uncorroborated ? html`<${UnverifiedIcon} />` : html`<${CheckIcon} />`}
          <//>
          <${Stat} value=${reach ? `~${peopleShort(reach.population)}` : "—"}
                   label=${reach ? `Most people near one hotspot, ${Math.round(reach.radius_km)} km`
                     : "No large town in reach"}>
            <${PeopleIcon} />
          <//>
        </div>`}

      <div class="ops-layout">
        <div class="ops-map-col">
          <${HotspotsMap} hotspots=${shown} focusId=${focus} onHover=${setFocus} />
          <${MapLegend} />
        </div>

        <div class="ops-list-col">
          ${data && hotspots.length > 0 && html`
            <div class="ops-filters" role="group" aria-label="Filter hotspots">
              <${Chip} on=${!band && !evidence} count=${hotspots.length}
                       onClick=${() => { setBand(null); setEvidence(null); }}>All<//>
              ${BANDS.map((b) => bandCount(b) > 0 && html`
                <${Chip} key=${b} on=${band === b} count=${bandCount(b)} tone="is-sev"
                         onClick=${() => setBand(band === b ? null : b)}>
                  <span class="sev-dot" data-severity=${b} aria-hidden="true"></span>${b}
                <//>`)}
              ${corroborated > 0 && uncorroborated > 0 && html`
                <${Fragment}>
                  <${Chip} on=${evidence === "ok"} count=${corroborated}
                           onClick=${() => setEvidence(evidence === "ok" ? null : "ok")}>
                    <${CheckIcon} />Corroborated<//>
                  <${Chip} on=${evidence === "citizen"} count=${uncorroborated}
                           onClick=${() => setEvidence(evidence === "citizen" ? null : "citizen")}>
                    <${UnverifiedIcon} />Citizen only<//>
                <//>`}
            </div>`}

          ${data && uncorroborated > 0 && html`
            <p class="ops-caveat">
              <${UnverifiedIcon} />
              <span><strong>${uncorroborated} rest on citizen reports alone</strong> — confidence
                capped until a satellite or station agrees.</span>
            </p>`}

          <div class="ops-list-panel">
            <div class="ops-list-head" aria-hidden="true">
              <span>Most confident first</span><span>Confidence</span><span>Verified</span>
            </div>

            ${!data && html`<${HotspotListSkeleton} />`}

            ${data && shown.length > 0 && html`
              <ul class="hotspot-list" aria-label="Hotspots, most confident first">
                ${rows.map((hotspot) => html`
                  <${HotspotCard} key=${hotspot.hotspot_id} hotspot=${hotspot}
                                  alert=${alerts[hotspot.hotspot_id]}
                                  active=${focus === hotspot.hotspot_id} onHover=${setFocus} />`)}
              </ul>`}

            ${data && shown.length > rows.length && html`
              <button type="button" class="ops-more" onClick=${() => setAll(true)}>
                Show all ${shown.length}
              </button>`}

            ${data && hotspots.length > 0 && shown.length === 0 && html`
              <p class="ops-nomatch">No hotspot matches these filters.</p>`}

            ${data && hotspots.length === 0 && html`<${NoHotspots} />`}
          </div>
        </div>
      </div>
    <//>`;
}

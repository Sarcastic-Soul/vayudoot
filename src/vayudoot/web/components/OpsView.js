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
 * mouse or without sight — everything the circles say is in the rows.
 *
 * The empty state is designed rather than defaulted. It is the state this
 * instance is in most of the time and the one a first-time reader is most
 * likely to hit, and the one sentence it must get right is that an empty map is
 * not clean air.
 */

import { html, Fragment } from "../lib/html.js";
import { navigate } from "../lib/router.js";
import { useHotspots } from "../lib/store.js";
import { plural, SOURCE_LABEL, SOURCE_BLURB } from "../lib/format.js";
import { HotspotsMap, MapLegend } from "./HotspotsMap.js";
import { HotspotCard } from "./HotspotCard.js";
import { HotspotListSkeleton } from "./Skeletons.js";
import { CameraIcon, HotspotIcon, SourceIcon } from "./Icons.js";

/* The order signals are introduced in: independent evidence first, because
   that is the half of the list that decides whether anything here is
   corroborated at all. */
const SOURCES = ["satellite", "ground_station", "citizen_report", "citizen_sensor"];

function SourceKey() {
  return html`
    <ul class="source-key">
      ${SOURCES.map((source) => {
        const Icon = SourceIcon[source];
        return html`
          <li key=${source} class=${source === "satellite" || source === "ground_station"
            ? "is-independent" : ""}>
            ${Icon && html`<${Icon} />`}
            <div>
              <strong>${SOURCE_LABEL[source]}</strong>
              <p>${SOURCE_BLURB[source]}</p>
            </div>
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
      <h3>Nothing is currently detected</h3>
      <p class="ops-empty-lead">
        <strong>An empty map is not clean air.</strong> It means no signal inside this
        instance's detection window has raised a hotspot — not that nothing is burning. Most
        of India is not covered by a ground station, and a place nobody has photographed and
        no satellite has passed over looks exactly like a place with nothing wrong.
      </p>
      <p class="ops-empty-note">
        A hotspot needs none of these in particular. Any one of them raises one on its own, and
        a citizen photograph <em>upgrades</em> a thermal anomaly into something describable that
        a complaint can be written about.
      </p>
      <${SourceKey} />
      <button type="button" class="primary" onClick=${() => navigate("report")}>
        <${CameraIcon} /> Report what you can see
      </button>
    </div>`;
}

export function OpsView() {
  const { data, error } = useHotspots();
  const hotspots = data || [];
  const uncorroborated = hotspots.filter((h) => !h.corroborated).length;

  /* One sentence, announced when it changes, carrying the two numbers that
     decide how the list should be read. The uncorroborated count is in it
     because a reader who never scrolls should still know how much of what is
     on screen rests only on public submissions. */
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
        <p>Places where pollution is being detected, built from citizen photographs, satellite
          thermal detections and ground-station readings together. Most confident first.</p>
      </header>

      <p class="ops-status" role="status">${status}</p>

      ${error && html`
        <p class="note is-bad">Could not reach the detection layer: ${error}
          ${data && data.length > 0 && " What is on screen is the last good reading."}</p>`}

      <div class="ops-layout">
        <div class="ops-map-col">
          <${HotspotsMap} hotspots=${hotspots} />
          <${MapLegend} />
        </div>

        <div class="ops-list-col">
          <div class="timeline-head">
            <h3 class="section-label" id="ops-list-label">Ranked by confidence</h3>
            ${data && hotspots.length > 0 && html`
              <p class="timeline-progress tnum">${plural(hotspots.length, "hotspot")}</p>`}
          </div>

          ${!data && html`<${HotspotListSkeleton} />`}

          ${data && uncorroborated > 0 && html`
            <p class="note is-limit ops-caveat">
              <strong>${uncorroborated} of these rest on public submissions alone.</strong>
              ${" "}Their confidence is capped until a satellite detection or a station reading
              agrees, however many more reports arrive — otherwise coordinated false reporting
              would manufacture a hotspot and a public map would become a weapon. Each one is
              marked below.
            </p>`}

          ${data && hotspots.length > 0 && html`
            <ul class="hotspot-list" aria-labelledby="ops-list-label">
              ${hotspots.map((hotspot) => html`
                <${HotspotCard} key=${hotspot.hotspot_id} hotspot=${hotspot} />`)}
            </ul>`}

          ${data && hotspots.length === 0 && html`<${NoHotspots} />`}
        </div>
      </div>
    <//>`;
}

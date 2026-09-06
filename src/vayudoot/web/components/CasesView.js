/* Everything submitted so far, as a map and as a list. The server returns them
 * newest first, which is the order a citizen wants: the case they just started
 * is the one they are looking for.
 *
 * Three states, all of which say something: cards, a skeleton the same shape
 * as the cards while the list is on its way, and — when there is genuinely
 * nothing — a panel that points at the one thing there is to do. */

import { useEffect, useRef } from "../vendor/hooks.mjs";
import { html, Fragment } from "../lib/html.js";
import { navigate } from "../lib/router.js";
import { useCases } from "../lib/store.js";
import { words, whereOf, shortWhen } from "../lib/format.js";
import { TILES, useLeafletMap } from "../lib/maps.js";
import { MapPane } from "./MapPane.js";
import { CameraIcon, InboxIcon, PinIcon } from "./Icons.js";
import { CaseListSkeleton } from "./Skeletons.js";

/* Leaflet popups take innerHTML when handed a string, so this hands it real
 * nodes instead: the case id is server data, but escaping should be structural
 * rather than remembered. */
function popupFor(c) {
  const box = document.createElement("div");
  const id = document.createElement("strong");
  id.textContent = c.case_id;
  box.append(id, document.createElement("br"), words(c.status));
  return box;
}

export function CasesView() {
  const cases = useCases();
  const layer = useRef(null);

  const [container, map] = useLeafletMap((node) => {
    const created = window.L.map(node).setView([22.35, 78.66], 4);
    window.L.tileLayer(TILES.url, TILES.options).addTo(created);
    layer.current = window.L.layerGroup().addTo(created);
    return created;
  });

  useEffect(() => {
    if (!map.current || !cases) return undefined;
    layer.current.clearLayers();
    const points = [];
    for (const c of cases) {
      const point = [c.report.latitude, c.report.longitude];
      points.push(point);
      window.L.marker(point)
        .bindPopup(popupFor(c))
        .on("click", () => navigate(c.case_id))
        .addTo(layer.current);
    }
    if (points.length) map.current.fitBounds(points, { maxZoom: 13, padding: [24, 24] });
    const timer = setTimeout(() => map.current && map.current.invalidateSize(), 50);
    return () => clearTimeout(timer);
  }, [cases]);

  const count = cases ? cases.length : 0;

  return html`
    <header class="page-head">
      <h2>Cases</h2>
      <p>Every report this instance has run, newest first. Open one to read the
        complaint it drafted and what it was based on.</p>
    </header>

    <${MapPane} paneClass="cases-map" containerRef=${container} />

    ${cases && count > 0 && html`
      <div class="timeline-head">
        <h3 class="section-label">
          ${count === 1 ? "1 case" : `${count} cases`}
        </h3>
      </div>`}

    <ul class="case-list">
      ${(cases || []).map((c) => html`
        <li key=${c.case_id}>
          <button type="button" onClick=${() => navigate(c.case_id)}>
            <span class="row">
              <strong>${c.case_id}</strong>
              <span class="pill" data-status=${c.status}>${words(c.status)}</span>
            </span>
            <span class="where"><${PinIcon} /><span>${whereOf(c)}</span></span>
            <span class="case-list-foot">
              <span class=${`kind${c.evidence ? "" : " is-waiting"}`}>
                ${c.evidence ? words(c.evidence.pollution_type) : "Still classifying…"}
              </span>
              <span class="when">${shortWhen(c.created_at)}</span>
            </span>
          </button>
        </li>`)}
    </ul>

    ${!cases && html`<${CaseListSkeleton} />`}

    ${cases && count === 0 && html`
      <${Fragment}>
        <div class="empty">
          <${InboxIcon} />
          <h3>No cases yet</h3>
          <p>A case starts with a photograph. Take one in front of the problem and this
            instance will classify it, corroborate it, work out who is responsible, and
            draft the complaint.</p>
          <button type="button" class="primary" onClick=${() => navigate("")}>
            <${CameraIcon} /> Report a pollution event
          </button>
        </div>
      <//>`}`;
}

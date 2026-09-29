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
import { apiUrl } from "../lib/api.js";
import { useCases, useClusters } from "../lib/store.js";
import { words, whereOf, shortWhen, isTerminal } from "../lib/format.js";
import { TILES, useLeafletMap } from "../lib/maps.js";
import { ClusterCard } from "./ClusterCard.js";
import { Flag } from "./Flag.js";
import { MapPane } from "./MapPane.js";
import { CameraIcon, InboxIcon, PatternIcon, PinIcon } from "./Icons.js";
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
  /* Patterns live here rather than behind a nav item of their own. A cluster is
     not a fourth kind of thing the citizen owns — it is what several of these
     cases turn out to be, computed from this same list — and a top-level
     destination that is empty until three reports coincide would read as a
     broken page far more often than as a feature. A filter would be worse
     still: it would return cases, and the centre, radius, span and reporter
     split that make a pattern an argument are not things a case card can say. */
  const { data: clusters } = useClusters();
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
  const tally = (pick) => (cases || []).filter(pick).length;
  const waiting = tally((c) => c.status === "awaiting_confirmation");
  const filed = tally((c) => ["filed", "acknowledged", "escalated"].includes(c.status));
  const closed = tally((c) => isTerminal(c));

  return html`
    <header class="page-head">
      <h2>Cases</h2>
      <p>Every report, newest first. Open one to read its complaint.</p>
      ${count > 0 && html`
        <ul class="case-stats-row" aria-label="Cases by state">
          <li><strong class="tnum">${count}</strong> total</li>
          ${waiting > 0 && html`
            <li class="is-waiting"><strong class="tnum">${waiting}</strong> waiting for you</li>`}
          <li><strong class="tnum">${filed}</strong> filed</li>
          <li><strong class="tnum">${closed}</strong> closed</li>
        </ul>`}
    </header>

    <${MapPane} paneClass="cases-map" containerRef=${container} />

    ${clusters && clusters.length > 0 && html`
      <section class="patterns">
        <div class="timeline-head">
          <h3 class="section-label">Repeat patterns</h3>
          <p class="timeline-progress tnum">
            ${clusters.length === 1 ? "1 pattern" : `${clusters.length} patterns`}
          </p>
        </div>
        <p class="patterns-lead">Same kind, same place, close in time — strongest first.</p>
        <ul class="cluster-list">
          ${clusters.map((cluster) => html`
            <${ClusterCard} key=${cluster.cluster_id} cluster=${cluster} />`)}
        </ul>
      </section>`}

    ${clusters && clusters.length === 0 && count > 0 && html`
      <p class="patterns-none-line">
        <${PatternIcon} />
        <span><strong>No repeat patterns yet.</strong> Several reports of one kind, at one
          place, get grouped here.</span>
      </p>`}

    ${cases && count > 0 && html`
      <div class="timeline-head">
        <h3 class="section-label">All cases</h3>
        <p class="timeline-progress tnum">${count === 1 ? "1 case" : `${count} cases`}</p>
      </div>`}

    <ul class="case-list">
      ${(cases || []).map((c) => html`
        <li key=${c.case_id}>
          <button type="button" class="case-card" onClick=${() => navigate(c.case_id)}>
            <span class=${`case-card-thumb${c.report.image_path ? "" : " is-empty"}`}>
              ${c.report.image_path
                ? html`<img src=${apiUrl(`/cases/${c.case_id}/photo`)} alt="" loading="lazy" />`
                : html`<${CameraIcon} />`}
              <span class="pill" data-status=${c.status}>${words(c.status)}</span>
            </span>
            <span class="case-card-body">
              <span class="case-card-top">
                <span class=${`case-card-kind${c.evidence ? "" : " is-waiting"}`}>
                  ${c.evidence ? words(c.evidence.pollution_type)
                    : c.status === "rejected" ? "Not taken up"
                      : isTerminal(c) ? "Stopped before classification" : "Still classifying…"}
                </span>
                <span class="when">${shortWhen(c.created_at)}</span>
              </span>
              <span class="where"><${PinIcon} /><span>${whereOf(c)}</span></span>
              <span class="case-card-foot">
                <span class="case-card-id">
                  ${c.jurisdiction && c.jurisdiction.country && html`
                    <${Flag} code=${c.jurisdiction.country} />`}
                  ${c.case_id}
                </span>
                <span class="case-card-go" aria-hidden="true">→</span>
              </span>
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
          <p>A case starts with a photograph or a voice note.</p>
          <button type="button" class="primary" onClick=${() => navigate("report")}>
            <${CameraIcon} /> Report a pollution event
          </button>
        </div>
      <//>`}`;
}

/* Everything submitted so far, as a map and as a list. The server returns them
 * newest first, which is the order a citizen wants: the case they just started
 * is the one they are looking for. */

import { useEffect, useRef } from "../vendor/hooks.mjs";
import { html } from "../lib/html.js";
import { navigate } from "../lib/router.js";
import { useCases } from "../lib/store.js";
import { words, whereOf } from "../lib/format.js";
import { TILES, useLeafletMap } from "../lib/maps.js";
import { MapPane } from "./MapPane.js";

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

  return html`
    <${MapPane} paneClass="cases-map" containerRef=${container} />
    <ul class="case-list">
      ${(cases || []).map((c) => html`
        <li key=${c.case_id}>
          <button type="button" onClick=${() => navigate(c.case_id)}>
            <span class="row">
              <strong>${c.case_id}</strong>
              <span class="pill" data-status=${c.status}>${words(c.status)}</span>
            </span>
            <span class="where">${whereOf(c)}</span>
            <span class="where">
              ${c.evidence ? words(c.evidence.pollution_type) : "classifying…"}
            </span>
          </button>
        </li>`)}
    </ul>
    <p class="muted empty" hidden=${!cases || cases.length > 0}>
      No cases yet. Submit a report to start one.
    </p>`;
}

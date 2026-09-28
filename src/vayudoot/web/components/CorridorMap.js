/* The corridor map: every corridor at once, or one corridor's outlook.
 *
 * One Leaflet instance serves both, and it outlives the change between them —
 * choosing a corridor flies the map from the whole network down to that line
 * rather than tearing one map down and building another. Which is drawn is
 * decided by `selectedId` alone.
 *
 * **A corridor is drawn as a broken line through its waypoints, and that line
 * is not a road.** The waypoints are sampling points, four to eight sparse
 * places along a real alignment, and the model is asked about each one. The
 * dashes say "joined for reading", not "drive here", and the legend says it in
 * words. A solid line would claim a route the data does not have.
 *
 * Once an outlook is in, each waypoint takes its risk band and each segment
 * takes the *worse* of its two ends: a stretch between a high and a low point
 * is read as a stretch you would want to know about, and the legend says that
 * too. Waypoints are numbered in corridor order so the map, the ribbon and the
 * list can all be read against each other without colour.
 *
 * Waypoints are drawn as fixed-size dots rather than as areas. That is not a
 * breach of hard constraint 7's area rule: a waypoint is a city the corridor
 * passes through, chosen by us, and never a detection at a place — there is no
 * facility under it to accuse.
 *
 * The hexes are literals for `HotspotsMap`'s reason: these sit on the same
 * light OpenStreetMap tiles in both themes, so a colour that followed the
 * theme would be wrong half the time.
 */

import { useEffect, useRef } from "../vendor/hooks.mjs";
import { html } from "../lib/html.js";
import { navigate } from "../lib/router.js";
import { INDIA_CENTRE, TILES, useLeafletMap } from "../lib/maps.js";
import { riskRank, RISK_BANDS, waypointIndex } from "../lib/format.js";
import { MapPane } from "./MapPane.js";

/* The severity ramp's map hexes, one band per risk step, separated by
   lightness as well as by hue. */
export const RISK_COLOUR = {
  low: "#3a6076",
  elevated: "#b07d10",
  high: "#c9541c",
  severe: "#9c2118",
};

const LINE = "#27425c";        // a corridor nobody has asked about yet
const LINE_DIM = "#6f7f8f";    // the others, while one is being looked at
const PENDING = "#6b6b73";

/* Leaflet takes innerHTML from a string, so a label is built as a node. */
function label(text) {
  const node = document.createElement("span");
  node.textContent = text;
  return node;
}

function boundsOf(corridors) {
  const points = corridors.flatMap((c) => c.waypoints);
  return points.length ? window.L.latLngBounds(points) : null;
}

export function CorridorMap({ corridors, selectedId, forecast, pending, highlightId,
  focusIndex, onPick }) {
  const layer = useRef(null);
  const lastFit = useRef("");

  const [container, map] = useLeafletMap((node) => {
    const created = window.L.map(node, { zoomSnap: 0.25 }).setView(INDIA_CENTRE, 4);
    window.L.tileLayer(TILES.url, TILES.options).addTo(created);
    layer.current = window.L.layerGroup().addTo(created);
    return created;
  });

  const selected = (corridors || []).find((c) => c.corridor_id === selectedId) || null;

  useEffect(() => {
    if (!map.current || !layer.current || !corridors) return undefined;
    const L = window.L;
    layer.current.clearLayers();

    if (!selected) {
      // ── the whole network ────────────────────────────────────────────
      for (const corridor of corridors) {
        const lit = highlightId === corridor.corridor_id;
        const dim = highlightId && !lit;
        const colour = dim ? LINE_DIM : LINE;
        // A white casing under the dots, so the line holds up over busy tiles.
        L.polyline(corridor.waypoints, {
          color: "#ffffff", weight: lit ? 9 : 7, opacity: dim ? 0.4 : 0.85,
          lineCap: "round", interactive: false,
        }).addTo(layer.current);
        const line = L.polyline(corridor.waypoints, {
          color: colour, weight: lit ? 5 : 3.5, opacity: dim ? 0.55 : 1,
          dashArray: "2 7", lineCap: "round", interactive: false,
        }).addTo(layer.current);
        // A fat invisible twin, so a thumb does not have to land on 3px.
        L.polyline(corridor.waypoints, { color: "#000", opacity: 0, weight: 18 })
          .bindTooltip(label(corridor.name), { sticky: true, className: "corridor-tip" })
          .on("click", () => navigate(`forecast/${corridor.corridor_id}`))
          .addTo(layer.current);
        for (const point of corridor.waypoints) {
          L.circleMarker(point, {
            radius: lit ? 5 : 4, color: colour, weight: 2, fillColor: "#ffffff",
            fillOpacity: 1, opacity: dim ? 0.6 : 1, interactive: false,
          }).addTo(layer.current);
        }
        if (lit) line.bringToFront();
      }
    } else {
      // ── one corridor, and its outlook if there is one ─────────────────
      const points = selected.waypoints;
      const byIndex = new Map();
      for (const f of forecast?.waypoint_forecasts || []) {
        const at = waypointIndex(selected, f);
        if (at >= 0) byIndex.set(at, f);
      }
      const riskAt = (i) => byIndex.get(i)?.risk || null;
      const worst = byIndex.size
        ? Math.max(...[...byIndex.values()].map((f) => riskRank(f.risk))) : -1;

      L.polyline(points, {
        color: "#ffffff", weight: 10, opacity: 0.8, lineCap: "round", interactive: false,
      }).addTo(layer.current);
      for (let i = 0; i < points.length - 1; i += 1) {
        const ends = [riskAt(i), riskAt(i + 1)].filter(Boolean);
        const band = ends.length ? ends.sort((a, b) => riskRank(b) - riskRank(a))[0] : null;
        L.polyline([points[i], points[i + 1]], {
          color: band ? RISK_COLOUR[band] : (pending ? PENDING : LINE),
          weight: band ? 6 : 4, opacity: band ? 0.85 : 0.8,
          dashArray: band ? "1 10" : "2 8", lineCap: "round", interactive: false,
          className: pending ? "corridor-pending" : "",
        }).addTo(layer.current);
      }

      points.forEach((point, i) => {
        const found = byIndex.get(i);
        const band = found?.risk || null;
        const fill = band ? RISK_COLOUR[band] : (pending ? PENDING : LINE);
        if (found && riskRank(band) === worst && worst > 0) {
          L.circleMarker(point, {
            radius: 19, color: fill, weight: 2, fill: false, opacity: 0.9,
            dashArray: "3 4", interactive: false,
          }).addTo(layer.current);
        }
        // A numbered disc rather than a tooltip over a circle: a tooltip is
        // anchored off-centre and the digit drifted out of its dot.
        const size = focusIndex === i ? 28 : 24;
        const disc = document.createElement("span");
        disc.textContent = String(i + 1);
        disc.style.background = fill;
        const dot = L.marker(point, {
          icon: L.divIcon({
            className: `waypoint-disc${pending ? " is-pending" : ""}`
              + `${focusIndex === i ? " is-focus" : ""}`,
            html: disc, iconSize: [size, size],
          }),
          title: `Waypoint ${i + 1}${band ? `: ${band} risk` : ""}`,
          keyboard: Boolean(onPick),
        }).addTo(layer.current);
        if (onPick) dot.on("click", () => onPick(i));
      });
    }

    // Fit only when what is being looked at changes, not on every redraw: a
    // reader who has zoomed in to read a segment should not be thrown back
    // out by a hover elsewhere.
    const fitKey = selected ? `one:${selected.corridor_id}` : `all:${corridors.length}`;
    const fit = (animate) => {
      if (!map.current) return;
      const bounds = boundsOf(selected ? [selected] : corridors);
      if (!bounds) return;
      map.current.flyToBounds(bounds, {
        padding: [36, 36], maxZoom: selected ? 9 : 6, animate, duration: 0.9,
      });
    };
    let timer = null;
    if (lastFit.current !== fitKey) {
      const first = !lastFit.current;
      lastFit.current = fitKey;
      const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
      fit(!first && !still);
      // A map built while hidden has no size yet; one late pass fixes it.
      if (first) {
        timer = setTimeout(() => {
          if (!map.current) return;
          map.current.invalidateSize();
          fit(false);
        }, 80);
      }
    }
    return () => clearTimeout(timer);
  }, [corridors, selected, forecast, pending, highlightId, focusIndex]);

  useEffect(() => {
    if (!map.current || !selected || focusIndex == null || focusIndex < 0) return;
    const point = selected.waypoints[focusIndex];
    if (point) map.current.panTo(point, { animate: true });
  }, [focusIndex]);

  return html`<${MapPane} paneClass="corridor-map" containerRef=${container} />`;
}

/* What the map is drawing, said on the page. The ramp only appears once there
   is an outlook to colour; before that, the one thing to say is what the lines
   are and are not. */
export function CorridorLegend({ withRisk }) {
  return html`
    <div class="legend corridor-legend">
      ${withRisk && html`
        <div class="legend-row">
          <span class="legend-label">Outlook</span>
          <ul>
            ${RISK_BANDS.map((band) => html`
              <li key=${band}>
                <span class="legend-swatch" data-risk=${band} aria-hidden="true"></span>${band}
              </li>`)}
          </ul>
        </div>`}
      <p class="legend-note">
        <span class="legend-dash" aria-hidden="true"></span>
        Dots are sampling points the model is asked about, not a route to drive; the line only
        joins them in order.${withRisk && " A segment takes the worse of its two ends."}
      </p>
    </div>`;
}

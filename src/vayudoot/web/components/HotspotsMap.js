/* The map an air-quality cell opens.
 *
 * **Every hotspot is drawn as a circle at its true `radius_km`, and nothing is
 * ever drawn as a pin.** That is hard constraint 7, not a style preference: a
 * marker on a point is a public accusation against whoever occupies that point,
 * and the system deliberately never names a responsible party. The server
 * already refuses to publish a radius under its floor; this is the half of that
 * rule which lives in the interface, and a future edit that "tidies" these
 * circles into markers would break it silently.
 *
 * Colour carries severity and nothing else. Confidence is not on the map at
 * all — it is a number in the list beside it — because two quantities on one
 * ramp become one quantity in the reader's head. What corroboration changes is
 * the *line*: an uncorroborated hotspot is drawn broken, because it rests only
 * on public submissions and the map should say so before anything is clicked.
 *
 * The hexes are literals rather than tokens for `ClusterView`'s reason: they
 * sit on OpenStreetMap tiles, which are the same light tiles in both themes,
 * so a colour that followed the theme would be wrong half the time.
 */

import { useEffect, useRef } from "../vendor/hooks.mjs";
import { html } from "../lib/html.js";
import { navigate } from "../lib/router.js";
import { INDIA_CENTRE, TILES, useLeafletMap } from "../lib/maps.js";
import { MapPane } from "./MapPane.js";

/* Four bands, separated by lightness as well as by hue so the ramp survives
   being printed, screenshotted, or looked at by someone who does not separate
   red from green. */
export const SEVERITY_COLOUR = {
  low: "#3a6076",
  moderate: "#b07d10",
  high: "#c9541c",
  severe: "#9c2118",
};

function ringStyle(hotspot) {
  const colour = SEVERITY_COLOUR[hotspot.severity] || SEVERITY_COLOUR.moderate;
  return hotspot.corroborated
    ? { color: colour, weight: 2.5, fillColor: colour, fillOpacity: 0.18 }
    // Broken line, thinner, barely filled: present on the map, visibly
    // provisional, and impossible to mistake for the solid ones.
    : { color: colour, weight: 2, dashArray: "6 5", fillColor: colour, fillOpacity: 0.07 };
}

/* Leaflet takes innerHTML when handed a string, so the popup is built from
   real nodes. Escaping should be structural rather than remembered. */
function popupFor(hotspot) {
  const box = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = hotspot.pollution_type.replace(/_/g, " ");
  const facts = document.createElement("div");
  facts.textContent = `${hotspot.severity} severity · ${Math.round(hotspot.confidence * 100)}% `
    + `confidence · ${hotspot.radius_km.toFixed(1)} km across`;
  box.append(title, facts);
  if (!hotspot.corroborated) {
    const flag = document.createElement("div");
    flag.textContent = "Citizen reports only — not independently corroborated.";
    flag.style.marginTop = "4px";
    flag.style.fontWeight = "600";
    box.append(flag);
  }
  return box;
}

export function HotspotsMap({ hotspots, paneClass = "ops-map", fitMaxZoom = 12 }) {
  const layer = useRef(null);

  const [container, map] = useLeafletMap((node) => {
    const created = window.L.map(node).setView(INDIA_CENTRE, 4);
    window.L.tileLayer(TILES.url, TILES.options).addTo(created);
    layer.current = window.L.layerGroup().addTo(created);
    return created;
  });

  useEffect(() => {
    if (!map.current || !layer.current) return undefined;
    layer.current.clearLayers();

    const drawn = [];
    for (const hotspot of hotspots || []) {
      const centre = [hotspot.centre_latitude, hotspot.centre_longitude];
      const ring = window.L.circle(centre, {
        ...ringStyle(hotspot),
        radius: hotspot.radius_km * 1000,
      })
        .bindPopup(popupFor(hotspot))
        .on("click", () => navigate(hotspot.hotspot_id))
        .addTo(layer.current);
      drawn.push(ring);
    }

    const fit = () => {
      if (!map.current || !drawn.length) return;
      const bounds = drawn.reduce((all, ring) => all.extend(ring.getBounds()),
        window.L.latLngBounds(drawn[0].getBounds()));
      map.current.fitBounds(bounds, { padding: [30, 30], maxZoom: fitMaxZoom });
    };

    fit();
    // A map that was hidden while it was built has no size yet, so the first
    // fit lands on a zero-height viewport. One late pass fixes it.
    const timer = setTimeout(() => {
      if (!map.current) return;
      map.current.invalidateSize();
      fit();
    }, 80);
    return () => clearTimeout(timer);
  }, [hotspots]);

  return html`<${MapPane} paneClass=${paneClass} containerRef=${container} />`;
}

/* What the colours and the broken line mean, said on the page rather than
   left to be inferred. Severity and corroboration are two legends because
   they are two variables; merging them into one row is how they get read as
   one thing. */
export function MapLegend() {
  return html`
    <div class="legend">
      <div class="legend-row">
        <span class="legend-label">Severity</span>
        <ul>
          ${["low", "moderate", "high", "severe"].map((band) => html`
            <li key=${band}>
              <span class="legend-swatch" data-severity=${band} aria-hidden="true"></span>${band}
            </li>`)}
        </ul>
      </div>
      <div class="legend-row">
        <span class="legend-label">Evidence</span>
        <ul>
          <li><span class="legend-ring is-solid" aria-hidden="true"></span>corroborated</li>
          <li>
            <span class="legend-ring is-dashed" aria-hidden="true"></span>citizen reports only
          </li>
        </ul>
      </div>
      <p class="legend-note">
        Circles are the hotspot's actual extent, never a point. Confidence is a separate number
        and is in the list, not on the map.
      </p>
    </div>`;
}

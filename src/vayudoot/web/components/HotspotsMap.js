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
 * **Zoomed out, a circle gets a glow, never a pin.** A 1 km circle on a map of
 * India is under a pixel, so the operations view would look empty. While a
 * circle draws smaller than `GLOW_BELOW_PX`, a soft disc of fixed screen size
 * sits over it so it can be found and clicked. The glow only exists while it
 * is *larger* than the true area — at that zoom it covers tens of kilometres —
 * so it can never point more precisely than the radius does, and it goes as
 * soon as the real circle is big enough to see.
 *
 * The hexes are literals rather than tokens for `ClusterView`'s reason: they
 * sit on OpenStreetMap tiles, which are the same light tiles in both themes,
 * so a colour that followed the theme would be wrong half the time.
 *
 * **Satellite layers go under the circles, never over them.** The operator can
 * swap the street map for yesterday's VIIRS pass and lay aerosol and fires on
 * top (`SatelliteControl`, `lib/gibs.js`), and every tile layer lives in
 * Leaflet's tile pane while the circles live in the overlay pane above it. Each
 * ring is drawn over a white halo of the same shape, so a dark-red ring stays
 * legible on dark farmland and a dashed ring stays visibly dashed.
 */

import { useEffect, useRef } from "../vendor/hooks.mjs";
import { html } from "../lib/html.js";
import { navigate } from "../lib/router.js";
import { INDIA_CENTRE, TILES, useLeafletMap } from "../lib/maps.js";
import { buildGibsLayers, useImagery } from "../lib/gibs.js";
import { MapPane } from "./MapPane.js";
import { SatelliteControl, SatelliteStamp } from "./SatelliteControl.js";
import { hotspotTitle } from "./HotspotMarks.js";

/* Four bands, separated by lightness as well as by hue so the ramp survives
   being printed, screenshotted, or looked at by someone who does not separate
   red from green. */
export const SEVERITY_COLOUR = {
  low: "#3a6076",
  moderate: "#b07d10",
  high: "#c9541c",
  severe: "#9c2118",
};

/* The halo under a ring: the same outline, white and wider, so the ring reads
   on dark imagery as well as on light tiles. Not interactive — the ring above
   it takes the click. */
function haloStyle(hotspot) {
  return {
    color: "#ffffff",
    weight: hotspot.corroborated ? 5.5 : 4.5,
    opacity: 0.85,
    dashArray: hotspot.corroborated ? null : "6 5",
    lineCap: "butt",
    fill: false,
    interactive: false,
  };
}

function ringStyle(hotspot) {
  const colour = SEVERITY_COLOUR[hotspot.severity] || SEVERITY_COLOUR.moderate;
  return hotspot.corroborated
    ? { color: colour, weight: 2.5, fillColor: colour, fillOpacity: 0.18 }
    // Broken line, thinner, barely filled: present on the map, visibly
    // provisional, and impossible to mistake for the solid ones.
    : { color: colour, weight: 2, dashArray: "6 5", fillColor: colour, fillOpacity: 0.07 };
}

/* Leaflet takes innerHTML when handed a string, so the tooltip is built from
   real nodes. Escaping should be structural rather than remembered. A hover
   tooltip rather than a popup, because a click opens the hotspot. */
function popupFor(hotspot) {
  const box = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = hotspotTitle(hotspot);
  const facts = document.createElement("div");
  facts.textContent = `${hotspot.severity} severity · ${Math.round(hotspot.confidence * 100)}% `
    + `confidence · ${hotspot.radius_km.toFixed(1)} km radius`;
  box.append(title, facts);
  if (!hotspot.corroborated) {
    const flag = document.createElement("div");
    flag.textContent = "Citizen reports only — not independently corroborated.";
    flag.style.color = "#8a4e07";
    flag.style.marginTop = "4px";
    flag.style.fontWeight = "600";
    box.append(flag);
  }
  return box;
}

const GLOW_BELOW_PX = 7;
const GLOW_PX = 9;

function glowStyle(hotspot, on = false) {
  const colour = SEVERITY_COLOUR[hotspot.severity] || SEVERITY_COLOUR.moderate;
  return {
    radius: on ? GLOW_PX + 5 : GLOW_PX,
    color: on ? "#ffffff" : colour,
    weight: on ? 2.5 : 1.5,
    opacity: 0.95,
    dashArray: hotspot.corroborated ? null : "3 3",
    fillColor: colour,
    fillOpacity: on ? 0.75 : 0.42,
  };
}

/* How many screen pixels a radius in kilometres spans at this zoom. */
function radiusPx(map, hotspot) {
  const metresPerPx = (40075016.686 * Math.cos((hotspot.centre_latitude * Math.PI) / 180))
    / 2 ** (map.getZoom() + 8);
  return (hotspot.radius_km * 1000) / metresPerPx;
}

function show(map, layer, on) {
  if (on && !map.hasLayer(layer)) layer.addTo(map);
  if (!on && map.hasLayer(layer)) map.removeLayer(layer);
}

export function HotspotsMap({ hotspots, paneClass = "ops-map", fitMaxZoom = 12, focusId = null,
  onHover }) {
  const layer = useRef(null);
  const rings = useRef(new Map());
  const glows = useRef(null);
  const street = useRef(null);
  const gibs = useRef(null);
  const drawnDate = useRef(null);
  const hoverRef = useRef(onHover);
  hoverRef.current = onHover;
  const imagery = useImagery();

  const [container, map] = useLeafletMap((node) => {
    const created = window.L.map(node).setView(INDIA_CENTRE, 4);
    street.current = window.L.tileLayer(TILES.url, { ...TILES.options, zIndex: 1 });
    gibs.current = buildGibsLayers(imagery.date);
    drawnDate.current = imagery.date;
    gibs.current.trueColour.setZIndex(1);
    gibs.current.aerosol.setZIndex(3);
    gibs.current.fires.setZIndex(4);
    gibs.current.reference.setZIndex(5);
    layer.current = window.L.layerGroup().addTo(created);
    glows.current = window.L.layerGroup().addTo(created);
    created.on("zoomend", () => placeGlows(created));
    return created;
  });

  /* Which layers are on, and for which day. Runs after the map exists, and
     again whenever the shared choice changes in any map's control. */
  useEffect(() => {
    const m = map.current;
    const g = gibs.current;
    if (!m || !g) return;
    const satellite = imagery.base === "satellite";
    if (drawnDate.current !== imagery.date) {
      g.setDate(imagery.date);
      drawnDate.current = imagery.date;
    }
    show(m, street.current, !satellite);
    show(m, g.trueColour, satellite);
    show(m, g.reference, satellite);
    show(m, g.aerosol, imagery.aerosol);
    show(m, g.fires, imagery.fires);
    m.getContainer().classList.toggle("is-satellite", satellite);
  }, [imagery]);

  /* Each glow shows only while its circle is too small to see. */
  function placeGlows(m) {
    for (const { glow, hotspot } of rings.current.values()) {
      const on = radiusPx(m, hotspot) < GLOW_BELOW_PX;
      if (on && !glows.current.hasLayer(glow)) glows.current.addLayer(glow);
      if (!on && glows.current.hasLayer(glow)) glows.current.removeLayer(glow);
    }
  }

  useEffect(() => {
    if (!map.current || !layer.current) return undefined;
    layer.current.clearLayers();
    glows.current.clearLayers();
    rings.current.clear();

    const drawn = [];
    for (const hotspot of hotspots || []) {
      const centre = [hotspot.centre_latitude, hotspot.centre_longitude];
      window.L.circle(centre, { ...haloStyle(hotspot), radius: hotspot.radius_km * 1000 })
        .addTo(layer.current);
      const ring = window.L.circle(centre, {
        ...ringStyle(hotspot),
        radius: hotspot.radius_km * 1000,
      })
        .bindTooltip(popupFor(hotspot), { direction: "top", sticky: true, opacity: 1 })
        .on("click", () => navigate(hotspot.hotspot_id))
        .on("mouseover", () => hoverRef.current && hoverRef.current(hotspot.hotspot_id))
        .on("mouseout", () => hoverRef.current && hoverRef.current(null))
        .addTo(layer.current);
      const glow = window.L.circleMarker(centre, glowStyle(hotspot))
        .bindTooltip(popupFor(hotspot), { direction: "top", opacity: 1 })
        .on("click", () => navigate(hotspot.hotspot_id))
        .on("mouseover", () => hoverRef.current && hoverRef.current(hotspot.hotspot_id))
        .on("mouseout", () => hoverRef.current && hoverRef.current(null));
      rings.current.set(hotspot.hotspot_id, { ring, glow, hotspot });
      drawn.push(ring);
    }

    const fit = () => {
      if (!map.current || !drawn.length) return;
      const bounds = drawn.reduce((all, ring) => all.extend(ring.getBounds()),
        window.L.latLngBounds(drawn[0].getBounds()));
      map.current.fitBounds(bounds, { padding: [30, 30], maxZoom: fitMaxZoom });
    };

    fit();
    placeGlows(map.current);
    // A map that was hidden while it was built has no size yet, so the first
    // fit lands on a zero-height viewport. One late pass fixes it.
    const timer = setTimeout(() => {
      if (!map.current) return;
      map.current.invalidateSize();
      fit();
      placeGlows(map.current);
    }, 80);
    return () => clearTimeout(timer);
  }, [hotspots]);

  /* The row being pointed at in the list lights its circle: heavier line,
     denser fill, drawn on top. Still the circle — the area — and nothing else. */
  useEffect(() => {
    for (const [id, { ring, glow, hotspot }] of rings.current) {
      const on = id === focusId;
      ring.setStyle(on
        ? { ...ringStyle(hotspot), weight: 4, fillOpacity: 0.38 }
        : ringStyle(hotspot));
      glow.setStyle(glowStyle(hotspot, on));
      glow.setRadius(glowStyle(hotspot, on).radius);
      if (on) { ring.bringToFront(); if (glows.current.hasLayer(glow)) glow.bringToFront(); }
    }
  }, [focusId, hotspots]);

  return html`
    <${MapPane} paneClass=${paneClass} containerRef=${container}>
      <${SatelliteControl} />
      <${SatelliteStamp} />
    <//>`;
}

/* What the colours and the broken line mean, said on the page rather than
   left to be inferred. Severity and corroboration are two groups because
   they are two variables; merging them is how they get read as one thing. */
export function MapLegend() {
  return html`
    <div class="ops-legend">
      <ul aria-label="Severity">
        ${["low", "moderate", "high", "severe"].map((band) => html`
          <li key=${band}>
            <span class="legend-swatch" data-severity=${band} aria-hidden="true"></span>${band}
          </li>`)}
      </ul>
      <ul aria-label="Evidence">
        <li><span class="legend-ring is-solid" aria-hidden="true"></span>Corroborated</li>
        <li><span class="legend-ring is-dashed" aria-hidden="true"></span>Citizen only</li>
      </ul>
      <p class="ops-legend-note">Each circle is an area, never an address.</p>
    </div>`;
}

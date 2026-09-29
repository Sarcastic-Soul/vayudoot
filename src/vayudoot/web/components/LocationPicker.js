/* A coordinate is not a human unit.
 *
 * The pin is the interface: it exists from the moment the page loads,
 * geolocation moves it if the citizen allows that, a place search moves it if
 * they do not, and dragging is always available. The latitude and longitude are
 * hidden fields the map writes into; the address underneath is what the citizen
 * actually reads back. */

import { useEffect, useRef, useState } from "../vendor/hooks.mjs";
import { html } from "../lib/html.js";
import { api } from "../lib/api.js";
import { INDIA_CENTRE, TILES, useLeafletMap } from "../lib/maps.js";
import { MapPane } from "./MapPane.js";
import { PlaceSearch } from "./PlaceSearch.js";

const RESTING = "Drag the pin to where the pollution is.";

/* Said once, behind the ⓘ: the pin is the most consequential field in the
   form, and the reason is worth a hover rather than a paragraph. */
const WHY_PIN = "The pin decides which authority receives the complaint, so put it where "
  + "the pollution is — not where you are standing later.";

const InfoIcon = () => html`
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <circle cx="12" cy="12" r="8.5" /><path d="M12 11v5.5M12 7.6v.2" />
  </svg>`;

export function LocationPicker({ point, onPoint }) {
  const [address, setAddress] = useState({ text: RESTING, loading: false });
  const marker = useRef(null);
  const describeToken = useRef(0);
  const pick = useRef(null);

  const [container, map] = useLeafletMap((node) => {
    const created = window.L.map(node).setView(INDIA_CENTRE, 4);
    window.L.tileLayer(TILES.url, TILES.options).addTo(created);
    marker.current = window.L.marker(INDIA_CENTRE, { draggable: true }).addTo(created);
    marker.current.on("dragend", () => {
      const { lat, lng } = marker.current.getLatLng();
      pick.current(lat, lng, { zoom: created.getZoom() });
    });
    // Tapping the map is faster than dragging on a phone.
    created.on("click", (e) => pick.current(e.latlng.lat, e.latlng.lng,
      { zoom: created.getZoom() }));
    return created;
  });

  async function describe(lat, lon) {
    const mine = ++describeToken.current;
    const fallback = `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
    setAddress({ text: "Finding the address…", loading: true });
    try {
      const geo = await api(`/geocode?lat=${lat}&lon=${lon}`);
      if (mine !== describeToken.current) return;
      setAddress({ text: geo.display_name || fallback, loading: false });
    } catch {
      if (mine === describeToken.current) setAddress({ text: fallback, loading: false });
    }
  }

  pick.current = (lat, lon, { zoom = 16 } = {}) => {
    onPoint({ latitude: lat, longitude: lon });
    if (map.current) {
      map.current.setView([lat, lon], zoom);
      marker.current.setLatLng([lat, lon]);
    }
    describe(lat, lon);
  };

  function locate({ quiet = false } = {}) {
    if (!navigator.geolocation) {
      if (!quiet) setAddress({ text: "This browser will not share a location. "
        + "Search or drag the pin.", loading: false });
      return;
    }
    if (!quiet) setAddress({ text: "Locating…", loading: true });
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => pick.current(coords.latitude, coords.longitude),
      (error) => {
        if (!quiet) setAddress({ text: `Could not get a location: ${error.message}. `
          + "Search or drag the pin.", loading: false });
      },
      { enableHighAccuracy: true, timeout: 15000 },
    );
  }

  // Quiet on load: a refused prompt is not an error worth reporting.
  useEffect(() => { locate({ quiet: true }); }, []);

  return html`
    <div class="field">
      <div class="field-head">
        <label for="place">
          Where is it?
          <span class="report-info" tabindex="0" role="img"
                aria-label=${WHY_PIN} title=${WHY_PIN}><${InfoIcon} /></span>
        </label>
        <button type="button" class="link" onClick=${() => locate()}>Use my location</button>
      </div>
      <${PlaceSearch} onPick=${(lat, lon) => pick.current(lat, lon)} />
      <${MapPane} paneClass="pick-map" containerRef=${container} />
      <p class=${`picked${address.loading ? " is-loading" : ""}${point ? " is-set" : ""}`}>
        ${address.text}
      </p>
      <input type="hidden" id="latitude" value=${point ? point.latitude.toFixed(6) : ""} />
      <input type="hidden" id="longitude" value=${point ? point.longitude.toFixed(6) : ""} />
    </div>`;
}

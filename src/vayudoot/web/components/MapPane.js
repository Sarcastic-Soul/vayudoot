/* The frame around a map, not the map itself.
 *
 * A 300px map is enough to confirm a pin and not enough to find one, so every
 * map can go full screen. The Leaflet instance is untouched by that: only the
 * size of its container changes, which is why the pin does not move and
 * nothing is re-created. */

import { useEffect, useState } from "../vendor/hooks.mjs";
import { html } from "../lib/html.js";
import { resizeMaps } from "../lib/maps.js";
import { ExpandIcon } from "./Icons.js";

export function MapPane({ paneClass, containerRef }) {
  const [full, setFull] = useState(false);

  useEffect(() => {
    document.body.classList.toggle("has-full-map", full);
    const timer = setTimeout(resizeMaps, 220);
    const onKey = (event) => { if (event.key === "Escape") setFull(false); };
    if (full) document.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("keydown", onKey);
      if (full) document.body.classList.remove("has-full-map");
    };
  }, [full]);

  const label = full ? "Close the expanded map" : "Expand the map";
  return html`
    <div class=${`map-wrap${full ? " is-full" : ""}`}>
      <div class=${paneClass} ref=${containerRef}></div>
      <button type="button" class="map-full" aria-label=${label} title=${label}
              onClick=${() => setFull((was) => !was)}>
        <${ExpandIcon} />
      </button>
    </div>`;
}

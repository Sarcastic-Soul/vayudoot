/* Leaflet is a global from a <script> tag and owns its own DOM, so Preact must
 * not re-render into a map container. Every map is created once against a ref
 * and then only ever spoken to imperatively. The registry exists so anything
 * that changes a container's size — the sidebar, full screen, the window — can
 * tell every live map at once. */

import { useEffect, useRef } from "../vendor/hooks.mjs";

const live = new Set();

export function resizeMaps() {
  for (const map of live) map.invalidateSize();
}

export const TILES = {
  url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  options: { maxZoom: 19, attribution: "© OpenStreetMap" },
};

export const INDIA_CENTRE = [22.35, 79.0];

/* `setup` is called once with the container element and returns the Leaflet
 * map. It is read through a ref so a re-render never rebuilds the map. */
export function useLeafletMap(setup) {
  const container = useRef(null);
  const map = useRef(null);
  const latest = useRef(setup);
  latest.current = setup;

  useEffect(() => {
    if (!window.L || map.current || !container.current) return undefined;
    map.current = latest.current(container.current);
    live.add(map.current);
    return () => {
      live.delete(map.current);
      map.current.remove();
      map.current = null;
    };
  }, []);

  return [container, map];
}

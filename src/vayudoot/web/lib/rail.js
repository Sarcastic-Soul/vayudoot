/* The sidebar collapses one notch: a labelled sidebar becomes a rail, and a
 * rail becomes icons only. It is available at every width that has a sidebar
 * at all — from 700px up. Below that the nav is a bar under the thumb and
 * there is nothing to collapse, which is why the control is hidden there in
 * CSS rather than conditionally rendered: the width is a CSS question. */

import { useEffect, useState } from "../vendor/hooks.mjs";
import { resizeMaps } from "./maps.js";

const KEY = "vayudoot.rail";

function stored() {
  try { return localStorage.getItem(KEY) === "1"; } catch { return false; }
}

export function useRail() {
  const [collapsed, setCollapsed] = useState(stored);

  useEffect(() => {
    document.body.classList.toggle("is-collapsed", collapsed);
    try { localStorage.setItem(KEY, collapsed ? "1" : "0"); } catch { /* private mode */ }
    // Leaflet needs telling once the grid has finished animating.
    const timer = setTimeout(resizeMaps, 280);
    return () => clearTimeout(timer);
  }, [collapsed]);

  return [collapsed, () => setCollapsed((was) => !was)];
}

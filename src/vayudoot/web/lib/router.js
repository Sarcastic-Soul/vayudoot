/* Hash routing.
 *
 * The hash is the only source of truth for which view is on screen, so a case
 * can be linked to, and so the back button walks the views the reader actually
 * visited. `history.pushState` fires no event of its own; `notify` is what
 * takes its place. */

import { useEffect, useState } from "../vendor/hooks.mjs";

const NAMED = ["report", "cases", "coverage"];
const listeners = new Set();

export function currentRoute() {
  const hash = decodeURIComponent(location.hash.slice(1));
  if (!hash) return { view: "report", caseId: null, clusterId: null };
  // Before the case prefix, though the two do not actually collide: a cluster
  // id is "VDC-", a case id is "VD-", and neither is a prefix of the other.
  if (hash.startsWith("VDC-")) return { view: "cluster", caseId: null, clusterId: hash };
  if (hash.startsWith("VD-")) return { view: "case", caseId: hash, clusterId: null };
  if (NAMED.includes(hash)) return { view: hash, caseId: null, clusterId: null };
  return { view: "report", caseId: null, clusterId: null };
}

/* `target` is what goes after the "#": "" for the report form, a view name, or
 * a case id. */
export function navigate(target) {
  if (location.hash.slice(1) === target) return notify();
  const url = target ? `#${target}` : location.pathname + location.search;
  history.pushState(null, "", url);
  notify();
}

function notify() {
  for (const listener of listeners) listener();
}

window.addEventListener("hashchange", notify);
window.addEventListener("popstate", notify);

export function useRoute() {
  const [route, setRoute] = useState(currentRoute);
  useEffect(() => {
    const onChange = () => setRoute(currentRoute());
    listeners.add(onChange);
    return () => listeners.delete(onChange);
  }, []);
  return route;
}

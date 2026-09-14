/* Hash routing.
 *
 * The hash is the only source of truth for which view is on screen, so a case
 * can be linked to, and so the back button walks the views the reader actually
 * visited. `history.pushState` fires no event of its own; `notify` is what
 * takes its place.
 *
 * The empty hash is the operations view, not the report form. That swap is the
 * v0.3 reframe made visible: the unit of work is a hotspot — a place where
 * pollution is happening — and the front door of the system is what is
 * happening now, not a form. Intake keeps a route of its own and loses
 * nothing; see `docs/SCOPE.md` under v0.3. */

import { useEffect, useState } from "../vendor/hooks.mjs";

const NAMED = ["ops", "report", "cases", "coverage"];

const HOME = { view: "ops", caseId: null, clusterId: null, hotspotId: null };
const listeners = new Set();

export function currentRoute() {
  const hash = decodeURIComponent(location.hash.slice(1));
  if (!hash) return HOME;
  // The two prefixed ids are tested before the bare case prefix: "VD-" is a
  // prefix of both "VDC-" and "VDH-", so order is load-bearing here.
  if (hash.startsWith("VDC-")) return { ...HOME, view: "cluster", clusterId: hash };
  if (hash.startsWith("VDH-")) return { ...HOME, view: "hotspot", hotspotId: hash };
  if (hash.startsWith("VD-")) return { ...HOME, view: "case", caseId: hash };
  if (NAMED.includes(hash)) return { ...HOME, view: hash };
  return HOME;
}

/* `target` is what goes after the "#": "" for the operations view, a view
 * name, or a case, cluster or hotspot id. */
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

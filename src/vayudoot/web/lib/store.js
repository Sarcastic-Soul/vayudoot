/* Server state.
 *
 * A pipeline run is minutes of model calls, so the browser never waits on a
 * submission: it posts the report, gets a case id back, and polls the case
 * while the stages advance. Everything on screen comes from the case object;
 * there is no second source of truth in the client. */

import { useEffect, useState } from "../vendor/hooks.mjs";
import { api } from "./api.js";
import { isFinished } from "./format.js";

const POLL_MS = 2500;

export function useCase(caseId) {
  const [record, setRecord] = useState(null);

  useEffect(() => {
    let live = true;
    let timer = null;
    setRecord(null);

    const again = () => { if (live) timer = setTimeout(tick, POLL_MS); };

    async function tick() {
      let found;
      try {
        found = await api(`/cases/${caseId}`);
      } catch {
        return again(); // transient, while the background run rewrites the file
      }
      if (!live) return;
      setRecord(found);
      if (!isFinished(found)) again();
    }

    tick();
    return () => { live = false; clearTimeout(timer); };
  }, [caseId]);

  return [record, setRecord];
}

export function useCases() {
  const [cases, setCases] = useState(null);
  useEffect(() => {
    let live = true;
    api("/cases")
      .then((found) => { if (live) setCases(found); })
      .catch(() => { if (live) setCases([]); });
    return () => { live = false; };
  }, []);
  return cases;
}

/* The authority table does not change while the page is open, so it is fetched
 * once and kept for the rest of the session. */
let coverageCache = null;

export function useCoverage() {
  const [state, setState] = useState(() => ({ data: coverageCache, error: null }));
  useEffect(() => {
    if (coverageCache) return undefined;
    let live = true;
    api("/authorities")
      .then((data) => { coverageCache = data; if (live) setState({ data, error: null }); })
      .catch((e) => { if (live) setState({ data: null, error: e.message }); });
    return () => { live = false; };
  }, []);
  return state;
}

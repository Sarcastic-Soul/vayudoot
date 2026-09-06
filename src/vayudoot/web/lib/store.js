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

/* What this instance will currently accept: the upload ceiling and what is
 * left of the day's model budget.
 *
 * Fetched rather than assumed so the form can refuse a 40 MB photograph before
 * it is uploaded over a phone connection, and can say that the day's reports
 * are gone before a citizen fills the form in. `reports_remaining_today` moves
 * with every submission, so this is re-read after one rather than cached: the
 * returned function is what asks again. Health is advisory — a failure here
 * leaves the form working exactly as it did before. */
export function useHealth() {
  const [health, setHealth] = useState(null);
  const [asked, setAsked] = useState(0);

  useEffect(() => {
    let live = true;
    api("/health")
      .then((data) => { if (live) setHealth(data); })
      .catch(() => { /* the form does not depend on it */ });
    return () => { live = false; };
  }, [asked]);

  return [health, () => setAsked((n) => n + 1)];
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

/* Repeat patterns across the whole store.
 *
 * Derived server-side on every call rather than stored, so this is a plain
 * fetch with no cache: a pattern that gained a member while the page was open
 * would otherwise keep showing yesterday's count. Cheap — the endpoint is
 * arithmetic over JSON files. */
export function useClusters() {
  const [state, setState] = useState({ data: null, error: null });
  useEffect(() => {
    let live = true;
    api("/clusters")
      .then((data) => { if (live) setState({ data, error: null }); })
      .catch((e) => { if (live) setState({ data: [], error: e.message }); });
    return () => { live = false; };
  }, []);
  return state;
}

/* The pattern one case belongs to, or null.
 *
 * Asked of the server rather than read from `case.cluster_id`. That field is a
 * record of what the drafting stage saw; a case filed as a one-off can become
 * the first member of a pattern weeks later, and every case created before
 * clustering existed has it empty. `key` re-asks when the case moves — a run
 * that has only just classified the photograph has only just become groupable. */
export function useCaseCluster(caseId, key) {
  const [cluster, setCluster] = useState(null);
  useEffect(() => {
    if (!caseId || !key) return undefined;
    let live = true;
    api(`/cases/${caseId}/cluster`)
      .then((found) => { if (live) setCluster(found || null); })
      .catch(() => { if (live) setCluster(null); });
    return () => { live = false; };
  }, [caseId, key]);
  return cluster;
}

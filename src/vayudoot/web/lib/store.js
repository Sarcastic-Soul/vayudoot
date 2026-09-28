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

/* Hotspots — places where pollution is happening.
 *
 * Derived server-side on every call, exactly like clusters, so there is no
 * cache here either: a hotspot gains a signal, moves its centre and changes
 * its confidence without anything being stored, and a cached copy would be
 * wrong within the hour.
 *
 * This is an operations view, so it re-asks on a slow timer rather than only
 * on mount. `POLL_MS` is the pipeline's tempo and far too quick for this; a
 * minute is roughly how often the underlying signals can actually change. */
const HOTSPOT_POLL_MS = 60000;

export function useHotspots() {
  const [state, setState] = useState({ data: null, error: null, at: null });

  useEffect(() => {
    let live = true;
    let timer = null;

    async function tick() {
      try {
        const data = await api("/hotspots");
        if (live) setState({ data, error: null, at: Date.now() });
      } catch (e) {
        // Keep whatever is on screen; an operations view that blanks itself
        // on one failed poll is worse than one showing a stale minute.
        if (live) setState((was) => ({ ...was, data: was.data || [], error: e.message }));
      }
      if (live) timer = setTimeout(tick, HOTSPOT_POLL_MS);
    }

    tick();
    return () => { live = false; clearTimeout(timer); };
  }, []);

  return state;
}

/* Every hotspot alert, newest first — only so the ranked list can mark a
 * hotspot that already has one pending or sent. Asked once per visit rather
 * than polled: an alert only changes when a person on the hotspot page acts,
 * and coming back to the list asks again. A failure shows no marks rather than
 * an error, because the list is complete without them. */
export function useAlerts() {
  const [alerts, setAlerts] = useState([]);
  useEffect(() => {
    let live = true;
    api("/alerts")
      .then((data) => { if (live && Array.isArray(data)) setAlerts(data); })
      .catch(() => { /* marks are a convenience */ });
    return () => { live = false; };
  }, []);
  return alerts;
}

/* One hotspot, asked for by id.
 *
 * `GET /hotspots/{id}` exists, unlike `/clusters/{id}`, so this asks for the
 * one rather than filtering the list. A 404 is a real answer and not a broken
 * link: detection is derived, so a hotspot stops existing the moment its
 * signals age out of the window or a case behind it is withdrawn. */
export function useHotspot(hotspotId) {
  const [state, setState] = useState({ data: null, error: null, gone: false });

  useEffect(() => {
    if (!hotspotId) return undefined;
    let live = true;
    setState({ data: null, error: null, gone: false });
    api(`/hotspots/${encodeURIComponent(hotspotId)}`)
      .then((data) => { if (live) setState({ data, error: null, gone: false }); })
      .catch((e) => {
        if (live) setState({ data: null, error: e.message, gone: e.status === 404 });
      });
    return () => { live = false; };
  }, [hotspotId]);

  return state;
}

/* Corridors — the economic corridors this instance forecasts along.
 *
 * Data, not code, on the server: a JSON edit adds one. It does not change while
 * the page is open, so it is fetched once per session like the authority table. */
let corridorCache = null;

export function useCorridors() {
  const [state, setState] = useState(() => ({ data: corridorCache, error: null }));
  useEffect(() => {
    if (corridorCache) return undefined;
    let live = true;
    api("/corridors")
      .then((data) => { corridorCache = data; if (live) setState({ data, error: null }); })
      .catch((e) => { if (live) setState({ data: [], error: e.message }); });
    return () => { live = false; };
  }, []);
  return state;
}

/* One corridor's outlook.
 *
 * This is the expensive call in the interface: one model call per waypoint, on
 * a free tier metered per request, and 20 to 60 seconds of waiting. Two things
 * follow. An answer is kept for as long as the server keeps it (30 minutes), so
 * walking back to the list and in again costs nothing. And a request that is
 * already in flight is *joined*, never repeated — a reader who leaves a
 * corridor after ten seconds and comes back must not buy the same answer twice.
 *
 * Failures are not kept, exactly as on the server: a quota trip should be
 * retryable, and `retry` is what asks again. */
const FORECAST_KEEP_MS = 30 * 60 * 1000;
const forecastDone = new Map();     // id -> { data, at }
const forecastFlight = new Map();   // id -> { promise, startedAt }

function askForecast(corridorId) {
  const flying = forecastFlight.get(corridorId);
  if (flying) return flying;
  const flight = {
    startedAt: Date.now(),
    promise: api(`/corridors/${encodeURIComponent(corridorId)}/forecast`)
      .then((data) => {
        // A partial corridor — some waypoints did not answer — is not kept, for
        // the server's reason: it does not cache one either, so asking again
        // can fill the gaps rather than replaying them for half an hour.
        const corridor = (corridorCache || []).find((c) => c.corridor_id === corridorId);
        const partial = corridor
          && (data.waypoint_forecasts || []).length < corridor.waypoints.length;
        if (!partial) forecastDone.set(corridorId, { data, at: Date.now() });
        return data;
      })
      .finally(() => forecastFlight.delete(corridorId)),
  };
  forecastFlight.set(corridorId, flight);
  return flight;
}

/* The outlook already in hand for a corridor, if any — for the list, which
   shows a band on a card only when it has one and never asks for it. */
export function knownForecast(corridorId) {
  const kept = forecastDone.get(corridorId);
  return kept && Date.now() - kept.at < FORECAST_KEEP_MS ? kept.data : null;
}

export function useCorridorForecast(corridorId) {
  const [state, setState] = useState(() => ({
    data: knownForecast(corridorId), error: null, status: 0, startedAt: null,
  }));
  const [asked, setAsked] = useState(0);

  useEffect(() => {
    if (!corridorId) return undefined;
    const kept = knownForecast(corridorId);
    if (kept) {
      setState({ data: kept, error: null, status: 0, startedAt: null });
      return undefined;
    }
    let live = true;
    const flight = askForecast(corridorId);
    setState({ data: null, error: null, status: 0, startedAt: flight.startedAt });
    flight.promise
      .then((data) => { if (live) setState({ data, error: null, status: 0, startedAt: null }); })
      .catch((e) => {
        if (!live) return;
        setState({ data: null, error: e.message, status: e.status || 0, startedAt: null });
      });
    return () => { live = false; };
  }, [corridorId, asked]);

  return [state, () => setAsked((n) => n + 1)];
}

/* Federation: who this node is, who it reads, and what it publishes.
 *
 * Three small reads, fetched together and independently — a neighbour being
 * down is ordinary on a federated network, so one failure must not blank the
 * panel. `/neighbours` is read live on the server, so it is re-asked on each
 * visit rather than cached here. */
export function useNetwork() {
  const [state, setState] = useState({ node: null, neighbours: null, feed: null,
    forecaster: null, errors: {} });

  useEffect(() => {
    let live = true;
    const read = (key, path) => api(path)
      .then((data) => { if (live) setState((was) => ({ ...was, [key]: data })); })
      .catch((e) => {
        if (live) {
          setState((was) => ({ ...was, [key]: false,
            errors: { ...was.errors, [key]: e.message } }));
        }
      });
    read("node", "/node");
    read("neighbours", "/neighbours");
    read("feed", "/feed");
    read("forecaster", "/forecaster");
    return () => { live = false; };
  }, []);

  return state;
}

/* The forecast ledger and its scores: how good the forecasts have been.
 *
 * Both reads are cheap — no model is called, the server only counts records
 * it already holds — so they are asked on every visit rather than cached. */

export function useForecastSkill() {
  const [state, setState] = useState({ skill: null, ledger: null, errors: {} });
  useEffect(() => {
    let live = true;
    const read = (key, path) => api(path)
      .then((data) => { if (live) setState((was) => ({ ...was, [key]: data })); })
      .catch((e) => {
        if (live) {
          setState((was) => ({ ...was, [key]: false,
            errors: { ...was.errors, [key]: e.message } }));
        }
      });
    read("skill", "/forecasts/skill");
    read("ledger", "/forecasts/ledger?limit=8");
    return () => { live = false; };
  }, []);
  return state;
}

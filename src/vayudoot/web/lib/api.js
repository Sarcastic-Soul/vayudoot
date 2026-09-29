/* The only place the interface talks to the server.
 *
 * FastAPI puts its message in `detail`; anything else is passed through as
 * text. Callers get an Error with something a person can read.
 *
 * The status code rides along on the Error rather than being folded into the
 * string, because a refused transition (409), an exhausted daily budget (429)
 * and an oversized photograph (413) are three different conversations to have
 * with a citizen, not three spellings of "that failed". */

/* Every server URL goes through here: `api()` below, and the handful of
 * places that hand a URL to the browser instead of fetching it — an <img>
 * `src`, a link to the open feed. `config.js` sets the base, and leaves it
 * empty when FastAPI served this page, so the path is used as it is.
 *
 * Read at each call rather than once at import, so nothing depends on which
 * script happened to run first. Static files (`/styles/`, `/vendor/`, the
 * components) are never passed through this: whoever serves the page serves
 * those too. */
export function apiUrl(path) {
  return `${window.VAYUDOOT_API_BASE || ""}${path}`;
}

/* ── waking the server ──────────────────────────────────────────────────
 * The public API runs on a free instance that sleeps after a quarter of an
 * hour idle, and the first request after that takes most of a minute. Seen
 * from the page, that is a map that never loads and no reason given. So when
 * the API is on another origin and the first request has not answered within
 * three seconds, the shell says why, and stops saying it as soon as anything
 * answers.
 *
 * Only the first wait counts. Later slow answers are the model at work — a
 * report takes a while on purpose — and are not the server asleep. Any HTTP
 * response ends the wait, an error status included: an error is still the
 * server answering. A network failure does not, since that is what a
 * half-woken instance can look like. Same-origin pages never show this: the
 * server that answered for the page is plainly awake. */

const WAKE_AFTER_MS = 3000;
let answered = false;
let wakeTimer = null;
let waking = false;
const wakeListeners = new Set();

function setWaking(value) {
  if (waking === value) return;
  waking = value;
  for (const listener of wakeListeners) listener(value);
}

function watchForSleep() {
  if (answered || wakeTimer || !window.VAYUDOOT_API_BASE) return;
  wakeTimer = setTimeout(() => { if (!answered) setWaking(true); }, WAKE_AFTER_MS);
}

function markAwake() {
  answered = true;
  clearTimeout(wakeTimer);
  setWaking(false);
}

/* For the banner: called with true when the wait starts showing and false
 * when it ends. Returns the unsubscribe. */
export function onWaking(listener) {
  wakeListeners.add(listener);
  listener(waking);
  return () => wakeListeners.delete(listener);
}

export async function api(path, opts) {
  watchForSleep();
  const response = await fetch(apiUrl(path), opts);
  markAwake();
  if (!response.ok) {
    const body = await response.text();
    let detail = body;
    try { detail = JSON.parse(body).detail ?? body; } catch { /* plain text */ }
    const failure = new Error(detail || `${response.status} ${response.statusText}`);
    failure.status = response.status;
    const retry = Number(response.headers.get("retry-after"));
    failure.retryAfter = Number.isFinite(retry) && retry > 0 ? retry : 0;
    throw failure;
  }
  const type = response.headers.get("content-type") || "";
  return type.includes("json") ? response.json() : response.text();
}

/* The lifecycle transitions all take a JSON note. One helper so the header is
 * not remembered at four call sites. */
export const postJSON = (path, body) =>
  api(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });

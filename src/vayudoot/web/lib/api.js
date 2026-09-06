/* The only place the interface talks to the server.
 *
 * FastAPI puts its message in `detail`; anything else is passed through as
 * text. Callers get an Error with something a person can read.
 *
 * The status code rides along on the Error rather than being folded into the
 * string, because a refused transition (409), an exhausted daily budget (429)
 * and an oversized photograph (413) are three different conversations to have
 * with a citizen, not three spellings of "that failed". */

export async function api(path, opts) {
  const response = await fetch(path, opts);
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

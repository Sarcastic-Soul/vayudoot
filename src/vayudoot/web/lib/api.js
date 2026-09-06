/* The only place the interface talks to the server.
 *
 * FastAPI puts its message in `detail`; anything else is passed through as
 * text. Callers get an Error with something a person can read. */

export async function api(path, opts) {
  const response = await fetch(path, opts);
  if (!response.ok) {
    const body = await response.text();
    let detail = body;
    try { detail = JSON.parse(body).detail ?? body; } catch { /* plain text */ }
    throw new Error(detail || `${response.status} ${response.statusText}`);
  }
  const type = response.headers.get("content-type") || "";
  return type.includes("json") ? response.json() : response.text();
}

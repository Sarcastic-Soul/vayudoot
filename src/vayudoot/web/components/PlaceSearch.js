/* Searching by name, for the citizen who will not share a location.
 *
 * Nominatim asks for at most one request a second, so this waits for a pause in
 * typing rather than firing on every keystroke. */

import { useEffect, useRef, useState } from "../vendor/hooks.mjs";
import { html } from "../lib/html.js";
import { api } from "../lib/api.js";

const DEBOUNCE_MS = 450;

export function PlaceSearch({ onPick }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState(null); // null while closed
  const box = useRef(null);

  useEffect(() => {
    const term = query.trim();
    if (term.length < 3) { setResults(null); return undefined; }
    let live = true;
    const timer = setTimeout(async () => {
      try {
        const { results: found } = await api(`/geocode?q=${encodeURIComponent(term)}`);
        if (live) setResults((found || []).filter((r) => !r.error));
      } catch {
        if (live) setResults(null);
      }
    }, DEBOUNCE_MS);
    return () => { live = false; clearTimeout(timer); };
  }, [query]);

  useEffect(() => {
    const onDocClick = (event) => {
      if (box.current && !box.current.contains(event.target)) setResults(null);
    };
    document.addEventListener("click", onDocClick);
    return () => document.removeEventListener("click", onDocClick);
  }, []);

  const choose = (hit) => {
    onPick(hit.latitude, hit.longitude);
    setQuery("");
    setResults(null);
  };

  return html`
    <div class="place-search" ref=${box}>
      <input type="text" id="place" placeholder="Search a place, or drag the pin"
             autocomplete="off" autocapitalize="off" spellcheck="false"
             value=${query} onInput=${(e) => setQuery(e.target.value)} />
      <ul class="place-results" hidden=${results === null}>
        ${results && results.length === 0 && html`<li class="muted">Nothing found</li>`}
        ${results && results.map((hit, i) => html`
          <li key=${i}>
            <button type="button" onClick=${() => choose(hit)}>${hit.display_name}</button>
          </li>`)}
      </ul>
    </div>`;
}

/* The forecast view: where air quality is about to degrade, and the network
 * that lets one node see smoke coming from another.
 *
 * The operations view answers "where is it bad now"; this one answers "where is
 * it about to be", along the economic corridors — a corridor being a supply
 * line and a population strip, named in the data rather than in code. The map
 * and the column beside it are the same corridors twice, as on the operations
 * view, and one Leaflet map serves both the list and a single corridor, so
 * choosing one flies the map down to it instead of rebuilding it.
 *
 * Nothing predictive is fetched until a corridor is chosen. An outlook is one
 * model call per waypoint on a free tier; a page that asked for every corridor
 * on load would spend a day's allowance on people scrolling past.
 *
 * Hard constraint 7 governs every word here, and the header says so before any
 * corridor is opened: these are a model's reasoning over public data, stated as
 * conditions, and never an official advisory. `CorridorOutlook.js` carries
 * the detail of how each outlook is labelled.
 */

import { useEffect, useState } from "../vendor/hooks.mjs";
import { html, Fragment } from "../lib/html.js";
import { navigate } from "../lib/router.js";
import { useCorridors, useCorridorForecast, useCoverage } from "../lib/store.js";
import { plural, borderCrossing, countryName } from "../lib/format.js";
import { CorridorMap, CorridorLegend } from "./CorridorMap.js";
import { CorridorCard, BorderBadge, crossingCodes } from "./CorridorCard.js";
import { Flag } from "./Flag.js";
import { OutlookPending, OutlookFailed, OutlookResult, ModelMark } from "./CorridorOutlook.js";
import { NetworkPanel } from "./NetworkPanel.js";
import { ForecastSkill } from "./ForecastSkill.js";
import { BackIcon } from "./Icons.js";

const NOT_OFFICIAL = "Conditions, not instructions. Not issued by IMD, CPCB, SAWS, DFFE, INMET, "
  + "IBAMA or any other government authority.";

/* The node's own country, from the authority table's `node_country`. The
   server lists only the corridors that run through it, so the list says so. */
function useNodeCountry() {
  const { data } = useCoverage();
  return data ? String(data.node_country || data.country || "").toUpperCase() : "";
}

function Overview({ corridors, error, onHover }) {
  const crossing = (corridors || []).filter((c) => borderCrossing(c)).length;
  const points = (corridors || []).reduce((n, c) => n + c.waypoints.length, 0);
  const home = useNodeCountry();
  return html`
    <${Fragment}>
      <div class="corridor-list-head">
        <h3 class="section-label" id="corridor-list-label">Economic corridors</h3>
        ${home && html`
          <span class="corridor-scope"
                title=${`Corridors through ${countryName(home)}, this node's country. A corridor `
                  + "elsewhere is forecast by the node that serves it."}>
            <${Flag} code=${home} size=${16} /></span>`}
      </div>
      ${corridors && corridors.length > 0 && html`
        <ul class="corridor-stats tnum" aria-label="Corridor totals">
          <li><strong>${corridors.length}</strong> corridors</li>
          <li title="Sampling points"><strong>${points}</strong> points</li>
          ${crossing > 0 && html`<li><strong>${crossing}</strong> cross-border</li>`}
        </ul>`}
      ${error && html`<p class="note is-bad">Could not read the corridors: ${error}</p>`}
      ${!corridors && html`
        <p class="visually-hidden" role="status">Loading the corridors.</p>
        <ul class="corridor-skeleton" aria-hidden="true">
          ${[0, 1, 2, 3].map((i) => html`<li key=${i} class="skeleton"></li>`)}
        </ul>`}
      ${corridors && html`
        <ul class="corridor-list" aria-labelledby="corridor-list-label">
          ${corridors.map((c) => html`
            <${CorridorCard} key=${c.corridor_id} corridor=${c} onHover=${onHover} />`)}
        </ul>`}
      ${corridors && corridors.length === 0 && !error && html`
        <p class="note">No corridors configured. Add one in <code>data/corridors.json</code>.</p>`}
    <//>`;
}

/* The corridor's name and where it runs. Above both columns rather than in
   one of them, so on a phone it is read before the map, not after it. The
   description is behind a disclosure: the route and the map already say where
   the corridor is, and the prose only says why it matters. */
function DetailHead({ corridor }) {
  const crossing = borderCrossing(corridor);
  return html`
    <div class="corridor-head">
      <button type="button" class="link back" onClick=${() => navigate("forecast")}>
        <${BackIcon} /> All corridors
      </button>
      <h2>${corridor.name}</h2>
      <p class="corridor-sub">
        ${crossing
          ? html`<${BorderBadge} countries=${crossingCodes(corridor, crossing)} />`
          : (corridor.countries || []).length === 1 && html`
            <${Flag} code=${corridor.countries[0]} size=${16} name=${true} />`}
        <span>${corridor.states.join(" · ")}</span>
        <span class="corridor-pts tnum">${plural(corridor.waypoints.length, "sampling point")}
        </span>
      </p>
      ${(corridor.waypoint_names || []).length > 1 && html`
        <p class="corridor-stops">${corridor.waypoint_names.map((name, i) => html`
          ${i > 0 && html`<span class="corridor-arrow" aria-hidden="true">→</span>`}
          <span key=${i}>${name.split(",")[0]}</span>`)}</p>`}
      ${corridor.description && html`
        <details class="why corridor-about">
          <summary>About this corridor</summary>
          <p>${corridor.description}</p>
        </details>`}
    </div>`;
}

function Detail({ corridor, state, retry, focus, onFocus }) {
  if (state.data) {
    return html`<${OutlookResult} corridor=${corridor} forecast=${state.data}
                                  focus=${focus} onFocus=${onFocus} />`;
  }
  if (state.error) {
    return html`<${OutlookFailed} error=${state.error} status=${state.status} onRetry=${retry} />`;
  }
  return html`<${OutlookPending} corridor=${corridor} startedAt=${state.startedAt} />`;
}

export function ForecastView({ corridorId }) {
  const { data: corridors, error } = useCorridors();
  const home = useNodeCountry();
  const [hover, setHover] = useState(null);
  const [focus, setFocus] = useState(null);
  const corridor = corridorId && corridors
    ? corridors.find((c) => c.corridor_id === corridorId) || null : null;
  const [state, retry] = useCorridorForecast(corridor ? corridor.corridor_id : null);

  useEffect(() => { setFocus(null); setHover(null); }, [corridorId]);

  const unknown = corridorId && corridors && !corridor;
  const answered = corridor && state.data?.waypoint_forecasts?.length > 0;

  return html`
    <div class="forecast">
      ${corridor && html`<${DetailHead} key=${corridor.corridor_id} corridor=${corridor} />`}
      ${!corridorId && html`
        <header class="page-head forecast-head">
          <h2>Where it is about to get worse</h2>
          <p>Model outlooks along economic corridors. Pick one to ask.</p>
          <p class="forecast-label">
            <${ModelMark}>Model-derived<//>
            <span title=${NOT_OFFICIAL}>Model output — not an IMD or CPCB forecast.</span>
          </p>
        </header>`}

      ${unknown && html`
        <div class="note is-bad">
          <p>No corridor <code>${corridorId}</code> on this node${home
            ? ` — it lists only corridors through ${countryName(home)}` : ""}.</p>
          <button type="button" class="link" onClick=${() => navigate("forecast")}>
            See every corridor</button>
        </div>`}

      <div class=${`forecast-layout${corridor ? " is-detail" : ""}`}>
        <div class="forecast-map-col">
          <${CorridorMap} corridors=${corridors} selectedId=${corridor?.corridor_id || null}
            forecast=${corridor ? state.data : null}
            pending=${Boolean(corridor && !state.data && !state.error)}
            highlightId=${hover} focusIndex=${focus} onPick=${setFocus} />
          <${CorridorLegend} withRisk=${answered} />
        </div>
        <div class="forecast-side">
          ${corridor
            ? html`<${Detail} key=${corridor.corridor_id} corridor=${corridor} state=${state}
                              retry=${retry} focus=${focus} onFocus=${setFocus} />`
            : html`<${Overview} corridors=${corridors} error=${error} onHover=${setHover} />`}
        </div>
      </div>

      ${!corridorId && html`<${ForecastSkill} />`}
      ${!corridorId && html`<${NetworkPanel} />`}
    </div>`;
}

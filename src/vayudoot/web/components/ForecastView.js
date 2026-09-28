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
 * conditions, and never a CPCB or IMD advisory. `CorridorOutlook.js` carries
 * the detail of how each outlook is labelled.
 */

import { useEffect, useState } from "../vendor/hooks.mjs";
import { html, Fragment } from "../lib/html.js";
import { navigate } from "../lib/router.js";
import { useCorridors, useCorridorForecast } from "../lib/store.js";
import { plural, borderCrossing } from "../lib/format.js";
import { CorridorMap, CorridorLegend } from "./CorridorMap.js";
import { CorridorCard, BorderBadge } from "./CorridorCard.js";
import { OutlookPending, OutlookFailed, OutlookResult, ModelMark } from "./CorridorOutlook.js";
import { NetworkPanel } from "./NetworkPanel.js";
import { BackIcon } from "./Icons.js";

function Overview({ corridors, error, onHover }) {
  const crossing = (corridors || []).filter((c) => borderCrossing(c)).length;
  return html`
    <${Fragment}>
      <div class="timeline-head">
        <h3 class="section-label" id="corridor-list-label">Economic corridors</h3>
        ${corridors && html`
          <p class="timeline-progress tnum">${plural(corridors.length, "corridor")}${crossing
            ? ` · ${crossing} cross-border` : ""}</p>`}
      </div>
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
        <p class="note">This instance has no corridors configured. They are data: an entry in
          <code>data/corridors.json</code> adds one.</p>`}
    <//>`;
}

/* The corridor's name and where it runs. Above both columns rather than in
   one of them, so on a phone it is read before the map, not after it. */
function DetailHead({ corridor }) {
  const crossing = borderCrossing(corridor);
  const [open, setOpen] = useState(false);
  return html`
    <div class="corridor-head">
      <button type="button" class="link back" onClick=${() => navigate("forecast")}>
        <${BackIcon} /> All corridors
      </button>
      <h2>${corridor.name}</h2>
      <p class="corridor-sub">
        ${crossing && html`<${BorderBadge} countries=${crossing} />`}
        <span>${corridor.states.join(" · ")}</span>
        <span class="tnum">${plural(corridor.waypoints.length, "sampling point")}</span>
      </p>
      ${corridor.description && html`
        <p class=${`corridor-lead${open ? "" : " is-clamped"}`} id="corridor-lead">
          ${corridor.description}</p>
        <button type="button" class="link lead-more" aria-expanded=${open}
                aria-controls="corridor-lead" onClick=${() => setOpen(!open)}>
          ${open ? "Show less" : "Read more"}</button>`}
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
          <p>An outlook for each economic corridor, reasoned by a model from public pollutant
            and wind forecasts and every hotspot upwind — this node's and its neighbours'.
            Choose a corridor to ask.</p>
          <p class="forecast-label">
            <${ModelMark}>Model-derived<//>
            <span>Conditions, not instructions. Not an official forecast, and not issued by
              CPCB, IMD or any government authority.</span>
          </p>
        </header>`}

      ${unknown && html`
        <div class="note is-bad">
          <p>There is no corridor called <code>${corridorId}</code> on this instance.</p>
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

      ${!corridorId && html`<${NetworkPanel} />`}
    </div>`;
}

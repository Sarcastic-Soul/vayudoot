/* One corridor in the list.
 *
 * The card leads with the shape of the corridor — its waypoints drawn to scale
 * as a small glyph — because a corridor is a line across a country before it is
 * a name, and the glyph is what lets the list be matched against the map
 * without reading. Once an outlook is in hand the glyph's dots take their risk
 * bands, so a list that has been explored carries its answers.
 *
 * A band is shown only when it is already known. The list never asks for an
 * outlook on its own: each one is a model call per waypoint on a free tier, and
 * opening a page should not spend six corridors' worth of them.
 */

import { html } from "../lib/html.js";
import { navigate } from "../lib/router.js";
import { knownForecast } from "../lib/store.js";
import { plural, borderCrossing, waypointIndex } from "../lib/format.js";
import { RISK_COLOUR } from "./CorridorMap.js";
import { BorderIcon, ModelIcon, ChevronIcon } from "./Icons.js";

/* The corridor's waypoints, projected to fit a square, north up. Longitude is
   scaled by the cosine of the latitude so a corridor does not look twice as
   wide as it is. */
export function RouteGlyph({ corridor, forecast, size = 56 }) {
  const pts = corridor.waypoints;
  if (!pts.length) return null;
  const midLat = pts.reduce((s, [lat]) => s + lat, 0) / pts.length;
  const k = Math.cos((midLat * Math.PI) / 180);
  const xs = pts.map(([, lon]) => lon * k);
  const ys = pts.map(([lat]) => -lat);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const span = Math.max(x1 - x0, y1 - y0) || 1;
  const pad = 7;
  const scale = (size - pad * 2) / span;
  const ox = pad + ((size - pad * 2) - (x1 - x0) * scale) / 2;
  const oy = pad + ((size - pad * 2) - (y1 - y0) * scale) / 2;
  const at = xs.map((x, i) => [ox + (x - x0) * scale, oy + (ys[i] - y0) * scale]);

  const bands = new Map();
  for (const f of forecast?.waypoint_forecasts || []) {
    const i = waypointIndex(corridor, f);
    if (i >= 0) bands.set(i, f.risk);
  }

  return html`
    <svg class="route-glyph" viewBox=${`0 0 ${size} ${size}`} width=${size} height=${size}
         aria-hidden="true">
      <polyline points=${at.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ")} />
      ${at.map(([x, y], i) => html`
        <circle key=${i} cx=${x.toFixed(1)} cy=${y.toFixed(1)} r=${bands.has(i) ? 3.6 : 2.6}
                style=${bands.has(i) ? `fill:${RISK_COLOUR[bands.get(i)]};stroke:none` : ""} />`)}
    </svg>`;
}

export function BorderBadge({ countries }) {
  const route = countries && countries.length > 1 ? countries.join(" → ") : null;
  return html`
    <span class="border-badge" title=${route ? `Crosses a national border: ${route}`
      : "Crosses a national border"}>
      <${BorderIcon} />Cross-border${route && html`<span class="border-route">${route}</span>`}
    </span>`;
}

export function CorridorCard({ corridor, onHover }) {
  const forecast = knownForecast(corridor.corridor_id);
  const crossing = borderCrossing(corridor);
  const answered = forecast?.waypoint_forecasts?.length > 0;

  return html`
    <li>
      <button type="button" class=${`corridor-card${crossing ? " is-cross-border" : ""}`}
              onClick=${() => navigate(`forecast/${corridor.corridor_id}`)}
              onMouseEnter=${() => onHover?.(corridor.corridor_id)}
              onMouseLeave=${() => onHover?.(null)}
              onFocus=${() => onHover?.(corridor.corridor_id)}
              onBlur=${() => onHover?.(null)}>
        <span class="corridor-glyph">
          <${RouteGlyph} corridor=${corridor} forecast=${forecast} />
        </span>
        <span class="corridor-main">
          <span class="corridor-title">
            <span class="corridor-name">${corridor.name}</span>
            ${crossing && html`<${BorderBadge} countries=${crossing} />`}
          </span>
          <span class="corridor-states">${corridor.states.join(" · ")}</span>
          ${corridor.description && html`
            <span class="corridor-desc">${corridor.description}</span>`}
          <span class="corridor-foot">
            <span class="tnum">${plural(corridor.waypoints.length, "sampling point")}</span>
            ${answered
              ? html`<span class="risk-chip" data-risk=${forecast.risk}>
                  <${ModelIcon} />${forecast.risk} outlook</span>`
              : html`<span class="corridor-ask">Ask the model<${ChevronIcon} /></span>`}
          </span>
        </span>
      </button>
    </li>`;
}

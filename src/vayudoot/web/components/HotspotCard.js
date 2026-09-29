/* One hotspot in the ranked list: a dense row, so thirty of them scan.
 *
 * The order of the rows is the server's — most confident first — so the row's
 * job is to make sure the number that put it there is never read on its own.
 * Severity is the coloured edge and its word; confidence is a number with a
 * meter in neutral ink, under a column labelled "Confidence"; and the
 * corroboration mark sits right beside it. On an uncorroborated hotspot that
 * mark says "Citizen only" in words and the meter is hatched: a capped number
 * shown without its cap is the presentation hard constraint 7 forbids.
 *
 * The second line is the quiet facts: the kind, the area it covers (a radius,
 * never a point), how old, where the signals came from, roughly how many
 * people are in reach, and whether an alert is waiting or sent — so an
 * operator scanning the list does not draft a second one.
 *
 * Hovering or focusing a row lights its circle on the map beside it.
 */

import { html } from "../lib/html.js";
import { navigate } from "../lib/router.js";
import {
  shortWhen, radiusLabel, sourceBreakdown, sourceLabel, kindLabel, corroborationOf, capital,
  isUnidentified,
  peopleShort, ALERT_STATUS_LABEL,
} from "../lib/format.js";
import { ConfidenceMeter, placeOf } from "./HotspotMarks.js";
import { SourceIcon, AlertMailIcon, CheckIcon, UnverifiedIcon, PeopleIcon } from "./Icons.js";

/* How old, as short as it can be said: a row has no room for "10 hours ago"
   beside a confidence meter on a phone. */
function age(iso) {
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return "";
  const mins = Math.max(0, Math.round((Date.now() - at) / 60000));
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return days < 7 ? `${days}d ago` : shortWhen(iso);
}

export function HotspotCard({ hotspot, alert, active = false, onHover }) {
  const id = hotspot.hotspot_id;
  const state = corroborationOf(hotspot);
  const place = placeOf(hotspot);
  const hover = (on) => onHover && onHover(on ? id : null);
  const exposure = hotspot.exposure;

  return html`
    <li>
      <button type="button" data-severity=${hotspot.severity}
              class=${`hs-row${active ? " is-active" : ""}${state.ok ? "" : " is-capped"}`}
              onClick=${() => navigate(id)}
              onMouseEnter=${() => hover(true)} onMouseLeave=${() => hover(false)}
              onFocus=${() => hover(true)} onBlur=${() => hover(false)}>
        <span class="hs-edge" aria-hidden="true"></span>

        <span class="hs-main">
          <span class="hs-title">${place || capital(kindLabel(hotspot))}</span>
          <span class="hs-sub">
            <span class="hs-sev"><span class="sev-dot" aria-hidden="true"></span>
              ${hotspot.severity}</span>
            <span class="tnum" title="Radius of the published area — never a point">
              ${radiusLabel(hotspot.radius_km)}</span>
            <span title=${`Last signal ${shortWhen(hotspot.last_seen_at)}`}>
              ${age(hotspot.last_seen_at)}</span>
          </span>
          <span class="hs-tags">
            ${place && html`<span class="hs-kind">
              ${isUnidentified(hotspot) ? "Unidentified" : capital(kindLabel(hotspot))}</span>`}
            ${sourceBreakdown(hotspot.source_counts).map(({ source, count, independent }) => {
              const Icon = SourceIcon[source];
              return html`
                <span key=${source} class=${`hs-tag${independent ? " is-independent" : ""}`}
                      title=${`${count} from ${sourceLabel(source).toLowerCase()}`}>
                  ${Icon && html`<${Icon} />`}<span class="tnum">${count}</span>
                  <span class="visually-hidden">${sourceLabel(source)}</span>
                </span>`;
            })}
            ${exposure && html`
              <span class="hs-tag" title=${`About ${exposure.population.toLocaleString("en-IN")} `
                + `people within ${Math.round(exposure.radius_km)} km — a coarse estimate`}>
                <${PeopleIcon} /><span class="tnum">~${peopleShort(exposure.population)}</span>
                <span class="visually-hidden">people in reach</span>
              </span>`}
            ${alert && html`
              <span class="hs-tag alert-chip" data-status=${alert.status}>
                <${AlertMailIcon} />${ALERT_STATUS_LABEL[alert.status] || alert.status}
              </span>`}
          </span>
        </span>

        <span class="hs-conf" title="Confidence — how sure the system is this is there">
          <span class="visually-hidden">Confidence</span>
          <${ConfidenceMeter} value=${hotspot.confidence} capped=${!state.ok} />
        </span>

        <span class=${`hs-corr${state.ok ? " is-ok" : " is-uncorroborated"}`} title=${state.label}>
          ${state.ok ? html`<${CheckIcon} />` : html`<${UnverifiedIcon} />`}
          <span class=${state.ok ? "visually-hidden" : "hs-corr-word"}>
            ${state.ok ? state.label : "Citizen only"}</span>
        </span>
      </button>
    </li>`;
}

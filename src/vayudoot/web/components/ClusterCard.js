/* One repeat pattern, as it appears in the list on the Cases view.
 *
 * The headline number is the report count, and it is labelled "reports" every
 * time. That is not a style choice: fifteen reports is the fact, fifteen
 * complainants is a claim the data cannot support, and a card that says "15"
 * beside a person icon would be making the second one silently. Who reported
 * gets its own line, in its own words, underneath.
 */

import { html } from "../lib/html.js";
import { navigate } from "../lib/router.js";
import { words, onDate, extentLabel, whoReported } from "../lib/format.js";
import { PatternIcon, PinIcon } from "./Icons.js";

export function ClusterCard({ cluster }) {
  const who = whoReported(cluster);
  return html`
    <li>
      <button type="button" onClick=${() => navigate(cluster.cluster_id)}>
        <span class="cluster-row">
          <span class="cluster-kind"><${PatternIcon} />${words(cluster.pollution_type)}</span>
          <span class="cluster-id tnum">${cluster.cluster_id}</span>
        </span>

        <span class="cluster-figures">
          <span class="figure">
            <strong class="tnum">${cluster.report_count}</strong>
            <span>reports</span>
          </span>
          <span class="figure">
            <strong class="tnum">${cluster.span_days < 1 ? "<1" : cluster.span_days}</strong>
            <span>${cluster.span_days === 1 ? "day" : "days"}</span>
          </span>
          <span class="figure">
            <strong class="tnum">${extentLabel(cluster.radius_km)}</strong>
            <span>across</span>
          </span>
        </span>

        ${cluster.address && html`
          <span class="where"><${PinIcon} /><span>${cluster.address}</span></span>`}

        <span class="cluster-foot">
          <span class="cluster-who">${who.line}</span>
          <span class="when">
            ${onDate(cluster.first_reported_at)} — ${onDate(cluster.last_reported_at)}
          </span>
        </span>
      </button>
    </li>`;
}

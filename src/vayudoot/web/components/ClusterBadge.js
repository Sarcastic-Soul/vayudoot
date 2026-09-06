/* The mark on a case that turns out not to be a one-off.
 *
 * It leads with this report's position in the group — "the 4th of 6" — because
 * that is the phrasing that carries weight in a complaint, and because it says
 * plainly that the case being read is one of several rather than the whole
 * story. It links to the pattern rather than restating it: everything else
 * about the group belongs on the group's own page.
 *
 * Drawn in `info`, not in the accent. A pattern is not good news and it is not
 * an action to take; it is a fact about the case that changes how it should be
 * read, which is the same weight the coverage warning above it carries.
 */

import { html } from "../lib/html.js";
import { navigate } from "../lib/router.js";
import { words, spanLabel, extentLabel, positionIn, ordinal, whoReported } from "../lib/format.js";
import { PatternIcon } from "./Icons.js";

export function ClusterBadge({ cluster, caseId }) {
  if (!cluster) return null;

  const at = positionIn(cluster, caseId);
  const who = whoReported(cluster);
  const headline = at
    ? `The ${ordinal(at)} of ${cluster.report_count} reports of `
      + `${words(cluster.pollution_type)} at this place.`
    : `${cluster.report_count} reports of ${words(cluster.pollution_type)} at this place.`;

  return html`
    <button type="button" class="cluster-badge"
            onClick=${() => navigate(cluster.cluster_id)}>
      <${PatternIcon} />
      <span class="cluster-badge-body">
        <span class="cluster-badge-head">${headline}</span>
        <span class="cluster-badge-note">
          ${who.line}, over ${spanLabel(cluster.span_days)},
          within ${extentLabel(cluster.radius_km)} of one another.
        </span>
      </span>
      <span class="cluster-badge-go">See the pattern</span>
    </button>`;
}

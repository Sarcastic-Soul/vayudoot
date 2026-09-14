/* One hotspot in the ranked list.
 *
 * The order of the rows is the server's — most confident first — so the card's
 * job is to make sure the number that put it there is never read on its own.
 * Confidence sits beside severity, both labelled, and the corroboration state
 * runs the full width underneath them. On an uncorroborated hotspot that band
 * is the loudest thing on the card by design: the confidence above it is
 * capped, and a capped number shown without its cap is the presentation hard
 * constraint 7 exists to forbid.
 */

import { html } from "../lib/html.js";
import { navigate } from "../lib/router.js";
import { words, shortWhen, plural, radiusLabel, sourceBreakdown, sourceLabel }
  from "../lib/format.js";
import { Figures, CorroborationBadge } from "./HotspotMarks.js";
import { SourceIcon } from "./Icons.js";

export function HotspotCard({ hotspot }) {
  const sources = sourceBreakdown(hotspot.source_counts);

  return html`
    <li>
      <button type="button" class="hotspot-card"
              onClick=${() => navigate(hotspot.hotspot_id)}>
        <span class="hotspot-row">
          <span class="hotspot-kind">${words(hotspot.pollution_type)}</span>
          <span class="hotspot-id tnum">${hotspot.hotspot_id}</span>
        </span>

        <${Figures} hotspot=${hotspot} />

        <${CorroborationBadge} hotspot=${hotspot} />

        <span class="hotspot-sources">
          ${sources.map(({ source, count, independent }) => {
            const Icon = SourceIcon[source];
            return html`
              <span key=${source} class=${`src${independent ? " is-independent" : ""}`}
                    title=${`${count} from ${sourceLabel(source).toLowerCase()}`}>
                ${Icon && html`<${Icon} />`}
                <span class="tnum">${count}</span>
                <span class="src-name">${sourceLabel(source)}</span>
              </span>`;
          })}
        </span>

        <span class="hotspot-foot">
          <span>${radiusLabel(hotspot.radius_km)} across · ${plural(hotspot.signal_count,
            "signal")}</span>
          <span class="when">${shortWhen(hotspot.last_seen_at)}</span>
        </span>
      </button>
    </li>`;
}

/* The case record: every transition, in the order it happened.
 *
 * This grows for the life of the case. A report that is filed, acknowledged,
 * escalated and finally resolved has a dozen entries before anybody has typed
 * a note, and the lifecycle is the half of the product that runs for months.
 * Three things stop it turning into a wall:
 *
 * - Each line arrives from the server as an ISO stamp followed by a sentence.
 *   Splitting the two lets the stamp be set as a time a person reads instead
 *   of thirty-two characters of machine time in the middle of the prose.
 * - The date is printed once per day rather than once per entry, because four
 *   things happening on one afternoon is one date and four times.
 * - Past a dozen entries the oldest are folded away behind a count. Not a
 *   scrolling box: this already sits inside a disclosure, and on a wide screen
 *   inside a sticky column that scrolls too, so a third nested scroller would
 *   be a trap on a touch screen. The entries hidden are the earliest ones —
 *   the pipeline stages, which the timeline above states in full anyway — and
 *   the recent end, where the case actually is, is always the part on screen.
 *
 * Order stays oldest first. This is a record of what was done on whose behalf,
 * and a record is read forwards. The latest entry is marked instead. */

import { useState } from "../vendor/hooks.mjs";
import { html } from "../lib/html.js";
import { onDate, atTime } from "../lib/format.js";

/* How many entries stay visible when the record is long, and the length past
 * which folding is worth doing at all. Below the threshold, a "show 2 more"
 * control costs a reader more than the two lines it hides. */
const KEEP = 8;
const FOLD_ABOVE = 12;

/* "2026-09-06T07:06:01+00:00 Filed to …" → the instant and the sentence.
 * Anything that does not start with a parseable stamp is shown whole rather
 * than mangled: the history is data from the server, not a format we control. */
function entryOf(line) {
  const gap = line.indexOf(" ");
  const at = gap > 0 ? Date.parse(line.slice(0, gap)) : NaN;
  if (Number.isNaN(at)) return { at: null, text: line };
  return { at, text: line.slice(gap + 1) };
}

export function CaseHistory({ record }) {
  const [all, setAll] = useState(false);

  const entries = record.history.map(entryOf);
  const folded = !all && entries.length > FOLD_ABOVE;
  const shown = folded ? entries.slice(entries.length - KEEP) : entries;
  const hidden = entries.length - shown.length;
  let lastDay = "";

  return html`
    <details class="history">
      <summary>
        Case history — ${entries.length} ${entries.length === 1 ? "entry" : "entries"}
      </summary>
      ${folded && html`
        <button type="button" class="quiet history-more" onClick=${() => setAll(true)}>
          Show ${hidden} earlier ${hidden === 1 ? "entry" : "entries"}
        </button>`}
      <ol>
        ${shown.map((entry, i) => {
          const day = entry.at === null ? "" : onDate(entry.at);
          const newDay = day !== "" && day !== lastDay;
          lastDay = day || lastDay;
          return html`
            <li key=${i} data-latest=${i === shown.length - 1 ? "true" : null}>
              ${newDay && html`<p class="history-day">${day}</p>`}
              <div class="history-entry">
                ${entry.at === null
                  ? null
                  : html`
                    <time class="history-time tnum"
                          datetime=${new Date(entry.at).toISOString()}>${atTime(entry.at)}</time>`}
                <span>${entry.text}</span>
              </div>
            </li>`;
        })}
      </ol>
    </details>`;
}

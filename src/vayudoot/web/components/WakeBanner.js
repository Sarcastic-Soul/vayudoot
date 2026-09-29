/* The note that the server is waking up.
 *
 * Shown only when the API is on another origin and its first answer is slow;
 * `lib/api.js` decides when, and says why there. It floats rather than
 * pushing the page down, because it is about the wait and not about anything
 * on the page, and it goes away by itself once the server answers — there is
 * nothing for the reader to do, so there is nothing to dismiss. */

import { useEffect, useState } from "../vendor/hooks.mjs";
import { html } from "../lib/html.js";
import { onWaking } from "../lib/api.js";

export function WakeBanner() {
  const [waking, setWaking] = useState(false);
  useEffect(() => onWaking(setWaking), []);

  /* The live region is always in the document, so a screen reader hears the
     sentence when it appears rather than missing a node that arrived whole. */
  return html`
    <div class="wake" role="status" aria-live="polite">
      ${waking && html`
        <p class="wake-note">
          <span class="wake-dot" aria-hidden="true"></span>
          <span><strong>Waking the server.</strong> The free instance sleeps when idle;
            this takes up to a minute.</span>
        </p>`}
    </div>`;
}

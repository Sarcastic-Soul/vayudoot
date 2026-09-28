/* One administrative region: the board that always answers for it, and the
 * municipal bodies that answer instead where the statute says so. Addresses are
 * the evidence for the safety claim, so they are always in the markup and the
 * stylesheet decides whether they are shown. */

import { html } from "../lib/html.js";
import { LanguageIcon } from "./Icons.js";

const Address = ({ email }) => (email ? html`<span class="addr">${email}</span>` : null);

/* India's regional regulator is a pollution control board; South Africa's
   is a provincial environment department and Brazil's a state agency. The
   wording follows the country so a Gauteng card does not read as Indian. */
export function RegionCard({ region, country = "IN" }) {
  const cities = region.municipal;
  const body = country === "IN" ? "board" : "agency";
  return html`
    <li>
      <div class="region-head">
        <h4>${region.region}</h4>
        <span class=${`chip${cities.length ? "" : " is-thin"}`}>
          ${cities.length
            ? `${cities.length} ${cities.length === 1 ? "city" : "cities"}`
            : `${country === "IN" ? "state" : "regional"} ${body} only`}
        </span>
      </div>

      <p class="region-board">
        ${region.state_board.name || "—"}${" "}
        <${Address} email=${region.state_board.email} />
      </p>

      ${region.local_language && html`
        <p class="region-lang">
          <${LanguageIcon} /> Complaints also drafted in ${region.local_language}
        </p>`}

      ${cities.length > 0 && html`
        <ul class="region-cities">
          ${cities.map((m) => html`
            <li key=${m.city}>
              <strong>${m.city}</strong>
              <span class="muted">${m.name}</span>
              <${Address} email=${m.email} />
            </li>`)}
        </ul>`}

      <p class="region-foot">
        ${cities.length
          ? `Anywhere else in ${region.region} resolves to the ${body} above.`
          : `Every report in ${region.region} resolves to the ${body} above, including the `
            + "waste and dust categories a municipal body would normally handle."}
      </p>
    </li>`;
}

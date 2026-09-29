/* One administrative region, as a row that opens: the name, the board that
 * always answers for it and how many cities have a municipal body of their
 * own, then — when opened — the bodies themselves. Addresses are the evidence
 * for the safety claim, so they are always in the markup and the stylesheet
 * decides whether they are shown.
 *
 * What an unlisted place in the region resolves to is said once, above the
 * list, rather than as the same sentence on forty rows. */

import { html } from "../lib/html.js";
import { LanguageIcon, BuildingIcon, LandmarkIcon, ChevronIcon } from "./Icons.js";

const Address = ({ email }) => (email ? html`<span class="addr">${email}</span>` : null);

/* India's regional regulator is a pollution control board; South Africa's
   is a provincial environment department and Brazil's a state agency. The
   wording follows the country so a Gauteng row does not read as Indian. */
export function RegionCard({ region, country = "IN", open = false }) {
  const cities = region.municipal;
  const body = country === "IN" ? "Board" : "Agency";
  const board = region.state_board.name || "—";

  return html`
    <li>
      <details class="region" open=${open}>
        <summary>
          <span class="region-text">
            <span class="region-name">${region.region}</span>
            <span class="region-board" title=${board}>${board}</span>
          </span>
          ${region.local_language && html`
            <span class="region-lang" title=${`Complaints also drafted in ${region.local_language}`}>
              <${LanguageIcon} /><span class="visually-hidden">
                Also drafted in ${region.local_language}</span>
            </span>`}
          <span class=${`chip${cities.length ? "" : " is-thin"}`}
                title=${cities.length ? null
                  : `Every report in ${region.region} resolves to the ${body.toLowerCase()}, `
                    + "including waste and dust"}>
            ${cities.length
              ? html`<${BuildingIcon} /> <span class="tnum">${cities.length}</span>
                  ${cities.length === 1 ? " city" : " cities"}`
              : `${body} only`}
          </span>
          <span class="region-caret" aria-hidden="true"><${ChevronIcon} /></span>
        </summary>

        <ul class="region-bodies">
          <li class="is-board">
            <${LandmarkIcon} />
            <span class="body-text">
              <span class="body-name">${board}</span>
              <${Address} email=${region.state_board.email} />
            </span>
            <span class="body-tier">${body}</span>
          </li>
          ${cities.map((m) => html`
            <li key=${m.city}>
              <${BuildingIcon} />
              <span class="body-text">
                <span class="body-name">${m.name}</span>
                <${Address} email=${m.email} />
              </span>
              <span class="body-tier is-city">${m.city}</span>
            </li>`)}
          ${region.local_language && html`
            <li class="is-lang">
              <${LanguageIcon} />
              <span class="body-text">Complaints also drafted in ${region.local_language}</span>
            </li>`}
        </ul>
      </details>
    </li>`;
}

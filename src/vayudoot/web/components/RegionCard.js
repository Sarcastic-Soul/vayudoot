/* One administrative region: the board that always answers for it, and the
 * municipal bodies that answer instead where the statute says so. Addresses are
 * the evidence for the safety claim, so they are always in the markup and the
 * stylesheet decides whether they are shown. */

import { html } from "../lib/html.js";

const Address = ({ email }) => (email ? html`<span class="addr">${email}</span>` : null);

export function RegionCard({ region }) {
  const cities = region.municipal;
  return html`
    <li>
      <div class="region-head">
        <h4>${region.region}</h4>
        <span class=${`chip${cities.length ? "" : " is-thin"}`}>
          ${cities.length
            ? `${cities.length} ${cities.length === 1 ? "city" : "cities"}`
            : "state board only"}
        </span>
      </div>

      <p class="region-board">
        ${region.state_board.name || "—"}${" "}
        <${Address} email=${region.state_board.email} />
      </p>

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
          ? `Anywhere else in ${region.region} resolves to the board above.`
          : `Every report in ${region.region} resolves to the board above, including the `
            + "waste and dust categories a municipal body would normally handle."}
      </p>
    </li>`;
}

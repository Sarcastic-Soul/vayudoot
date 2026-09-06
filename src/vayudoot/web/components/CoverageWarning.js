/* An authority the table did not actually have must not read like one it did. */

import { html } from "../lib/html.js";
import { navigate } from "../lib/router.js";

export function CoverageWarning({ jurisdiction }) {
  const coverage = jurisdiction && jurisdiction.coverage;
  if (!coverage || coverage === "exact") return null;

  const headline = coverage === "generic"
    ? "This region is not in the authority table."
    : "No local authority for this city is in the table.";
  const note = jurisdiction.coverage_note
    || "The complaint resolved to a broader authority than the statute names.";

  return html`
    <p class="coverage-warning" data-coverage=${coverage}>
      <strong>${headline}</strong> ${note}${" "}
      <button type="button" class="link" onClick=${() => navigate("coverage")}>
        See what is covered
      </button>
    </p>`;
}

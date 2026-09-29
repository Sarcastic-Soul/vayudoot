/* Which country's law this case is under, in what language, and what kind of
 * clock it runs on.
 *
 * Three facts a citizen reads before anything else about the paperwork, and
 * the third is the one that must not be got wrong. Where a statute gives the
 * authority a deadline, the window is a legal duty. Where none does — South
 * Africa's Air Quality Act, every Brazilian environmental agency — the number
 * is this system's own follow-up interval, and calling it a deadline would be
 * a false legal claim. So the chip says which it is in words, and when it is
 * not statutory a one-line "No legal deadline applies here" stays visible, with
 * the authority table's own note saying why behind a "Why?" disclosure.
 */

import { html } from "../lib/html.js";
import { caseCountry, countryName, isStatutory } from "../lib/format.js";
import { FlagMark } from "./Flag.js";
import { ClockIcon, LanguageIcon } from "./Icons.js";

export function CaseJurisdiction({ record }) {
  const j = record && record.jurisdiction;
  if (!j) return null;
  const code = caseCountry(j);
  const language = j.local_language || (record.complaint && record.complaint.local_language)
    || "";
  const statutory = isStatutory(j);
  const days = j.response_window_days;

  return html`
    <section class="case-juris" aria-label="Jurisdiction">
      <ul class="case-juris-chips">
        <li title="Country"><${FlagMark} code=${code} size=${18} />${countryName(code)}</li>
        <li title="Language of the complaint">
          <${LanguageIcon} />${language || html`<span class="muted">English only</span>`}
        </li>
        <li class=${statutory ? "is-statutory" : "is-followup"}
            title=${statutory ? "Response window" : "Follow-up interval"}>
          <${ClockIcon} />
          <span class="tnum">${days ? `${days} days` : "—"}</span>
          <span class=${`juris-tag${statutory ? "" : " is-not"}`}>
            ${statutory ? "statutory" : "not statutory"}</span>
        </li>
      </ul>
      ${!statutory && html`
        <div class="juris-note">
          <strong>No legal deadline applies here.</strong>${" "}
          <details class="why why-case">
            <summary>Why?</summary>
            ${j.response_window_note
              || "No statute sets a time for this authority to answer. The interval is this "
                + "system's suggested follow-up, not a statutory period."}
          </details>
        </div>`}
    </section>`;
}

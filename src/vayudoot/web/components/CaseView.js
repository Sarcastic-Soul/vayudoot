/* One case, from the photograph to the filed envelope. Everything on screen is
 * read out of the case object the server returns; the poll in `useCase` keeps
 * it current while the pipeline runs.
 *
 * The order on the page is an argument about importance: what state the case
 * is in, then the complaint it produced, then the evidence that supports it,
 * then the paperwork. On a wide screen the complaint moves to its own column
 * and stays put while the working scrolls beside it. */

import { useEffect, useState } from "../vendor/hooks.mjs";
import { html, Fragment } from "../lib/html.js";
import { api } from "../lib/api.js";
import { navigate } from "../lib/router.js";
import { useCase } from "../lib/store.js";
import { whereOf } from "../lib/format.js";
import { BackIcon, PinIcon } from "./Icons.js";
import { CaseActions } from "./CaseActions.js";
import { CaseStatusSkeleton } from "./Skeletons.js";
import { Complaint } from "./Complaint.js";
import { CoverageWarning } from "./CoverageWarning.js";
import { StatusBanner } from "./CaseStatus.js";
import { Timeline } from "./Timeline.js";

const FILED = ["filed", "escalated"];

export function CaseView({ caseId }) {
  const [record, setRecord] = useCase(caseId);
  const [envelope, setEnvelope] = useState("");
  const status = record ? record.status : null;

  useEffect(() => {
    if (!status || !FILED.includes(status)) { setEnvelope(""); return undefined; }
    let live = true;
    api(`/cases/${caseId}/envelope`)
      .then((text) => { if (live) setEnvelope(text); })
      .catch(() => { /* nothing filed yet */ });
    return () => { live = false; };
  }, [caseId, status]);

  return html`
    <div class="case-head">
      <button type="button" class="link back" onClick=${() => navigate("cases")}>
        <${BackIcon} /> All cases
      </button>
      <h2>${caseId}</h2>
      ${record && html`
        <p class="case-where"><${PinIcon} /><span>${whereOf(record)}</span></p>`}
    </div>

    <${StatusBanner} record=${record} />

    ${record && html`<${CoverageWarning} jurisdiction=${record.jurisdiction} />`}

    ${!record && html`<${CaseStatusSkeleton} />`}

    ${record && html`
      <div class="case-grid">
        <div class="case-col">
          ${record.report.image_path && html`
            <${Fragment}>
              <h3 class="section-label">The photograph reported</h3>
              <img class="case-photo" src=${`/cases/${caseId}/photo`}
                   alt="The photograph submitted with this report" />
            <//>`}

          <${Timeline} record=${record} />
        </div>

        <div class="case-col">
          ${record.complaint && html`<${Complaint} complaint=${record.complaint} />`}
          <${CaseActions} record=${record} onUpdate=${setRecord} />

          ${envelope && html`
            <details class="envelope" open>
              <summary>Filed envelope (sandbox outbox)</summary>
              <pre>${envelope}</pre>
            </details>`}

          <details class="history">
            <summary>Case history — ${record.history.length} entries</summary>
            <ol>${record.history.map((line, i) => html`<li key=${i}>${line}</li>`)}</ol>
          </details>
        </div>
      </div>`}`;
}

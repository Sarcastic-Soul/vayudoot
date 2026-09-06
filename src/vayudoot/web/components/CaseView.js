/* One case, from the photograph to the filed envelope. Everything on screen is
 * read out of the case object the server returns; the poll in `useCase` keeps
 * it current while the pipeline runs. */

import { useEffect, useState } from "../vendor/hooks.mjs";
import { html } from "../lib/html.js";
import { api } from "../lib/api.js";
import { navigate } from "../lib/router.js";
import { useCase } from "../lib/store.js";
import { words, whereOf } from "../lib/format.js";
import { CaseActions } from "./CaseActions.js";
import { Complaint } from "./Complaint.js";
import { CoverageWarning } from "./CoverageWarning.js";
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
        ← All cases
      </button>
      <h2>${caseId}</h2>
      <div class="case-meta" aria-live="polite">
        <span class="pill" data-status=${status}>${status ? words(status) : "—"}</span>
        <span class="muted">${record ? whereOf(record) : ""}</span>
      </div>
    </div>

    ${record && html`<${CoverageWarning} jurisdiction=${record.jurisdiction} />`}

    <div class="case-grid">
      <div class="case-col">
        ${record && record.report.image_path && html`
          <img class="case-photo" src=${`/cases/${caseId}/photo`} alt="Submitted photograph" />`}
        ${record && html`<${Timeline} record=${record} />`}
      </div>

      <div class="case-col">
        ${record && record.complaint && html`<${Complaint} complaint=${record.complaint} />`}
        ${record && html`<${CaseActions} record=${record} onUpdate=${setRecord} />`}

        ${envelope && html`
          <details class="envelope" open>
            <summary>Filed envelope (sandbox outbox)</summary>
            <pre>${envelope}</pre>
          </details>`}

        <details class="history">
          <summary>Case history</summary>
          <ul>${record && record.history.map((line, i) => html`<li key=${i}>${line}</li>`)}</ul>
        </details>
      </div>
    </div>`;
}

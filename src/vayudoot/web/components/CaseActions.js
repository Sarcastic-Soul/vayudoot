/* The human-in-the-loop gate. Nothing leaves the machine until a person has
 * read the draft and pressed the button; escalation only appears once the
 * statutory window has actually lapsed, because the server refuses it before
 * then. */

import { useState } from "../vendor/hooks.mjs";
import { html } from "../lib/html.js";
import { api } from "../lib/api.js";
import { escalationDue } from "../lib/format.js";

export function CaseActions({ record, onUpdate }) {
  const [busy, setBusy] = useState("");
  const [failure, setFailure] = useState("");

  async function act(path, working) {
    setBusy(working);
    setFailure("");
    try {
      onUpdate(await api(`/cases/${record.case_id}/${path}`, { method: "POST" }));
    } catch (e) {
      setFailure(e.message);
    } finally {
      setBusy("");
    }
  }

  const confirming = record.status === "awaiting_confirmation";
  const escalating = escalationDue(record);
  if (!confirming && !escalating && !failure) return null;

  return html`
    <div class="actions">
      ${confirming && html`
        <button type="button" class="primary" disabled=${Boolean(busy)}
                onClick=${() => act("confirm", "Filing…")}>
          ${busy || "Confirm and file this complaint"}
        </button>
        <p class="help">Filing writes to the local sandbox outbox.
          No authority is contacted.</p>`}
      ${escalating && html`
        <button type="button" class="primary" disabled=${Boolean(busy)}
                onClick=${() => act("escalate", "Escalating…")}>
          ${busy || `Escalate to ${record.jurisdiction.escalation_authority}`}
        </button>
        <p class="help">The response window has lapsed with no acknowledgement.</p>`}
      ${failure && html`<p class="error">Failed: ${failure}</p>`}
    </div>`;
}

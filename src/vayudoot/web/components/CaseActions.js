/* The human-in-the-loop gate. Nothing leaves the machine until a person has
 * read the draft and pressed the button; escalation only appears once the
 * statutory window has actually lapsed, because the server refuses it before
 * then.
 *
 * This is the most consequential control in the product — a citizen
 * authorising a formal complaint to a regulator — so it is a block that says
 * what pressing it does, not a button floating under a card. It is drawn in
 * the accent rather than in red: the decision is serious, but it is not a
 * warning, and a control that looks like a warning gets clicked past. */

import { useState } from "../vendor/hooks.mjs";
import { html } from "../lib/html.js";
import { api } from "../lib/api.js";
import { escalationDue } from "../lib/format.js";
import { SendIcon, EscalateIcon, LockIcon } from "./Icons.js";

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

  const authority = record.jurisdiction && record.jurisdiction.authority_name;

  return html`
    <div class="actions">
      ${confirming && html`
        <p class="eyebrow">Your decision</p>
        <p class="decision">
          Filing sends this complaint${authority ? ` to ${authority}` : ""} as it is written
          above. Nothing has gone anywhere yet.
        </p>
        <button type="button" class="primary" disabled=${Boolean(busy)}
                onClick=${() => act("confirm", "Filing…")}>
          ${busy || html`<${SendIcon} /> Confirm and file this complaint`}
        </button>
        <p class="help">
          <${LockIcon} />
          <span>Filing writes to the local sandbox outbox. No authority is contacted.</span>
        </p>`}
      ${escalating && html`
        <p class="eyebrow">Nobody answered</p>
        <p class="decision">
          The ${record.jurisdiction.response_window_days}-day response window has lapsed with
          no acknowledgement. Escalating raises the case a tier.
        </p>
        <button type="button" class="primary" disabled=${Boolean(busy)}
                onClick=${() => act("escalate", "Escalating…")}>
          ${busy || html`
            <${EscalateIcon} /> Escalate to ${record.jurisdiction.escalation_authority}`}
        </button>`}
      ${failure && html`<p class="error">Could not do that: ${failure}</p>`}
    </div>`;
}

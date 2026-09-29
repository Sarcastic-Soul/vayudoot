/* Everything a person can do to a case, and nothing they cannot.
 *
 * Two blocks, because there are two kinds of act here and collapsing them into
 * one row of buttons would flatten the difference:
 *
 * - The decision. Filing sends a formal complaint to a regulator; escalating
 *   raises it a tier. These are the most consequential controls in the
 *   product, so each is a block that says what pressing it does, drawn in the
 *   accent rather than in red — the decision is serious, but it is not a
 *   warning, and a control that looks like a warning gets clicked past.
 * - The record. Acknowledging, resolving and withdrawing send nothing; they
 *   tell the tracker what happened in the world it cannot see. Quieter,
 *   secondary, and each behind a note field, because a lifecycle entry with no
 *   reason on it is worth very little a month later.
 *
 * Availability is computed, never guessed. Every control is gated on the same
 * rule the server enforces — the `*_FROM` tuples in `lifecycle.py` and
 * `filing.escalation_due`, mirrored in `lib/format.js` — so a control that
 * would come back 409 is not drawn at all. If one is drawn and the server
 * refuses it anyway, because the case moved under us while the page was open,
 * the server's own sentence is shown and the case is re-read: the interface
 * corrects itself rather than arguing.
 *
 * Withdrawal is the exception to "one press". It is destructive in effect and
 * terminal in fact. So it sits apart, below a rule, in the quietest weight on
 * the card; it opens into what it actually means; and it will not go through
 * without a reason typed in. Two deliberate steps and no dialog — a modal on a
 * 390px screen held in one hand is a fight. */

import { useEffect, useRef, useState } from "../vendor/hooks.mjs";
import { html, Fragment } from "../lib/html.js";
import { api, postJSON } from "../lib/api.js";
import {
  canAcknowledge, canResolve, canWithdraw, escalationDue, isTerminal, onDate, todayISO,
  isStatutory, windowPhrase, capital,
} from "../lib/format.js";
import {
  SendIcon, EscalateIcon, LockIcon, ReplyIcon, ResolvedIcon, WithdrawIcon,
} from "./Icons.js";

/* Mirrors NOTE_MAX in api.py. These are one-line records of what happened,
 * not correspondence, and the server refuses a longer one rather than
 * truncating it — so the field stops at the same number. */
const NOTE_MAX = 500;

const WHY_RECORD = "Nothing reaches this tracker on its own. Tell it when the authority "
  + "replies, or when the problem stops, and the case stays honest about where it is.";

/* Local midnight on the chosen day, as an instant, never in the future.
 *
 * A reader east of UTC has a local "today" that begins hours before UTC's, so
 * sending their date at 00:00Z can land ahead of now — which would quietly
 * hand the authority a few extra hours of response window. Clamped rather than
 * refused: the citizen picked a real day, and the clamp is invisible. */
function respondedAt(day) {
  if (!day) return null;
  const at = Date.parse(`${day}T00:00:00Z`);
  if (Number.isNaN(at)) return null;
  return new Date(Math.min(at, Date.now())).toISOString();
}

export function CaseActions({ record, onUpdate }) {
  const [open, setOpen] = useState("");
  const [busy, setBusy] = useState("");
  const [failure, setFailure] = useState(null);
  const [note, setNote] = useState("");
  const [day, setDay] = useState(todayISO);
  const firstField = useRef(null);

  /* Opening a panel moves focus into it, so a keyboard or screen-reader user
     lands in the field they just asked for rather than being left on a button
     whose panel has appeared somewhere below them. */
  useEffect(() => { if (open && firstField.current) firstField.current.focus(); }, [open]);

  /* …and closing one puts focus back on the control that opened it. Found by
     id rather than held as a node, because the withdraw control is replaced by
     its own panel rather than sitting above it, so the button that comes back
     is not the button that went away. */
  function toggle(panel) {
    const closing = !panel || open === panel;
    const was = open;
    setFailure(null);
    setNote("");
    setOpen(closing ? "" : panel);
    if (closing && was) {
      setTimeout(() => {
        const opener = document.getElementById(`${was}-toggle`);
        if (opener) opener.focus();
      }, 0);
    }
  }

  /* `where` is which block owns the outcome, so a refusal is reported under
     the control that caused it rather than at the bottom of the page. */
  async function send(where, path, working, body) {
    setBusy(working);
    setFailure(null);
    try {
      const url = `/cases/${record.case_id}/${path}`;
      onUpdate(body === undefined
        ? await api(url, { method: "POST" })
        : await postJSON(url, body));
      setOpen("");
      setNote("");
    } catch (error) {
      setFailure({ where, message: error.message });
      /* A refused transition means this page is looking at a stale case. Take
         the server's word for where the case actually is. */
      if (error.status === 409) {
        try { onUpdate(await api(`/cases/${record.case_id}`)); } catch { /* keep what we have */ }
      }
    } finally {
      setBusy("");
    }
  }

  const problem = (where) => (failure && failure.where === where
    ? html`
      <p class="error" role="alert">
        <strong>That did not go through.</strong> ${failure.message}
      </p>`
    : null);

  const today = todayISO();
  const confirming = record.status === "awaiting_confirmation";
  const escalating = escalationDue(record);
  const acknowledging = canAcknowledge(record);
  const resolving = canResolve(record);
  const withdrawing = canWithdraw(record);

  /* A finished case offers nothing: every transition would be refused, and a
     row of dead controls is a worse answer than no controls at all. The banner
     above says how it ended. The one thing still worth drawing is the refusal
     that just told us the case had ended. */
  if (isTerminal(record)) {
    return failure
      ? html`<section class="updates">${problem(failure.where)}</section>`
      : null;
  }

  const authority = record.jurisdiction && record.jurisdiction.authority_name;
  const days = record.jurisdiction && record.jurisdiction.response_window_days;
  /* Where no law sets a deadline, the number is this system's follow-up
     interval, and no sentence here may call it a legal window. */
  const statutory = isStatutory(record.jurisdiction);
  const futureDated = Boolean(day) && day > today;
  const working = Boolean(busy);

  const counter = (value) => (value.length > NOTE_MAX - 100
    ? html`<p class="note-count tnum" aria-hidden="true">
        ${value.length} of ${NOTE_MAX} characters</p>`
    : null);

  const cancel = html`
    <button type="button" class="quiet" onClick=${() => toggle("")}>Cancel</button>`;

  return html`
    <${Fragment}>
      ${(confirming || escalating) && html`
        <div class="actions">
          ${confirming && html`
            <${Fragment}>
              <p class="eyebrow">Your decision</p>
              <p class="decision">
                Files the draft above, as written${authority
                  ? html`, to <strong>${authority}</strong>` : ""}.
              </p>
              <button type="button" class="primary" disabled=${working}
                      onClick=${() => send("decision", "confirm", "Filing…")}>
                ${busy || html`<${SendIcon} /> Confirm and file this complaint`}
              </button>
              <p class="help case-sandbox">
                <${LockIcon} />
                <span>Sandbox · written to a local outbox, no authority is contacted</span>
              </p>
            <//>`}

          ${escalating && html`
            <${Fragment}>
              <p class="eyebrow">
                ${record.status === "acknowledged" ? "Nothing has followed" : "Nobody answered"}
              </p>
              <p class="decision">
                ${record.status === "acknowledged"
                  ? `Acknowledged on ${onDate(record.acknowledged_at)}; the ${days}-day `
                    + `${statutory ? "window" : "follow-up interval (not statutory)"} since `
                    + "has passed with no action. "
                  : `${capital(windowPhrase(record.jurisdiction))} has `
                    + `${statutory ? "lapsed" : "passed"} with no acknowledgement. `}
                Escalating raises the case a tier.
              </p>
              <button type="button" class="primary" disabled=${working}
                      onClick=${() => send("decision", "escalate", "Escalating…")}>
                ${busy || html`
                  <${EscalateIcon} /> Escalate to ${record.jurisdiction.escalation_authority}`}
              </button>
            <//>`}

          ${problem("decision")}
        </div>`}

      ${(acknowledging || resolving || withdrawing) && html`
        <section class="updates" aria-labelledby=${acknowledging || resolving
          ? "updates-heading" : null}>
          ${(acknowledging || resolving) && html`
            <${Fragment}>
              <h3 class="section-label" id="updates-heading">
                Record what happened
                <span class="case-info" tabindex="0" role="img"
                      aria-label=${WHY_RECORD} title=${WHY_RECORD}>ⓘ</span>
              </h3>
              <div class="update-row">
                ${acknowledging && html`
                  <button type="button" class="secondary" id="acknowledge-toggle"
                          aria-expanded=${open === "acknowledge"}
                          aria-controls="panel-acknowledge"
                          onClick=${() => toggle("acknowledge")}>
                    <${ReplyIcon} /> Record a response
                  </button>`}
                ${resolving && html`
                  <button type="button" class="secondary" id="resolve-toggle"
                          aria-expanded=${open === "resolve"}
                          aria-controls="panel-resolve" onClick=${() => toggle("resolve")}>
                    <${ResolvedIcon} /> Close as resolved
                  </button>`}
              </div>
            <//>`}

          ${open === "acknowledge" && html`
            <div class="update-panel" id="panel-acknowledge">
              <p class="decision">
                A reply doesn't close the case: it restarts the
                ${days ? ` ${days}-day` : ""}${statutory ? " clock" : " follow-up interval"}${" "}
                from the day it arrived.
              </p>
              <div class="field">
                <label for="ack-day">When did the response arrive?</label>
                <input type="date" id="ack-day" max=${today} value=${day} ref=${firstField}
                       aria-describedby="ack-day-help"
                       onInput=${(e) => setDay(e.target.value)} />
                <p class="help" id="ack-day-help">
                  ${futureDated
                    ? html`<span class="error">A response cannot have arrived after today.</span>`
                    : "The date on the reply, or today if it has just come in."}
                </p>
              </div>
              <div class="field">
                <label for="ack-note">
                  What did they say? <span class="muted">(optional)</span>
                </label>
                <textarea id="ack-note" rows="3" maxlength=${NOTE_MAX} value=${note}
                          placeholder="Inspection scheduled for the 14th."
                          onInput=${(e) => setNote(e.target.value)}></textarea>
                ${counter(note)}
              </div>
              <div class="panel-buttons">
                <button type="button" class="primary" disabled=${working || futureDated}
                        onClick=${() => send("acknowledge", "acknowledge", "Recording…", {
                          note, responded_at: respondedAt(day),
                        })}>
                  ${busy || "Record the response"}
                </button>
                ${cancel}
              </div>
              ${problem("acknowledge")}
            </div>`}

          ${open === "resolve" && html`
            <div class="update-panel" id="panel-resolve">
              <p class="decision">
                Only once the pollution itself has stopped. The clock stops and nothing more
                is filed.
              </p>
              <div class="field">
                <label for="resolve-note">
                  What actually happened? <span class="muted">(optional)</span>
                </label>
                <textarea id="resolve-note" rows="3" maxlength=${NOTE_MAX} value=${note}
                          ref=${firstField}
                          placeholder="Site inspected on the 14th, burning stopped."
                          onInput=${(e) => setNote(e.target.value)}></textarea>
                ${counter(note)}
              </div>
              <div class="panel-buttons">
                <button type="button" class="primary" disabled=${working}
                        onClick=${() => send("resolve", "resolve", "Closing…", { note })}>
                  ${busy || "Close this case as resolved"}
                </button>
                ${cancel}
              </div>
              ${problem("resolve")}
            </div>`}

          ${withdrawing && html`
            <div class=${`withdraw${open === "withdraw" ? " is-open" : ""}`}>
              ${open === "withdraw"
                ? html`
                  <div class="update-panel" id="panel-withdraw">
                    <p class="eyebrow">Withdrawing this complaint</p>
                    <p class="decision">
                      Ends the case for good — no filing, escalation or reopening.
                      ${record.filed_at
                        ? " The complaint already sent is not recalled, but tracking stops."
                        : " Nothing has been sent, and now nothing will be."}
                    </p>
                    <div class="field">
                      <label for="withdraw-note">Why are you withdrawing it?</label>
                      <textarea id="withdraw-note" rows="3" maxlength=${NOTE_MAX} value=${note}
                                ref=${firstField} aria-describedby="withdraw-note-help"
                                placeholder="Reported the wrong location."
                                onInput=${(e) => setNote(e.target.value)}></textarea>
                      <p class="help" id="withdraw-note-help">
                        Required. It is the last entry on the record.
                      </p>
                      ${counter(note)}
                    </div>
                    <div class="panel-buttons">
                      <button type="button" class="danger" disabled=${working || !note.trim()}
                              onClick=${() => send("withdraw", "withdraw", "Withdrawing…",
                                { note })}>
                        ${busy || html`<${WithdrawIcon} /> Withdraw this complaint for good`}
                      </button>
                      ${cancel}
                    </div>
                    ${problem("withdraw")}
                  </div>`
                : html`
                  <button type="button" class="quiet withdraw-open" id="withdraw-toggle"
                          aria-expanded="false" aria-controls="panel-withdraw"
                          onClick=${() => toggle("withdraw")}>
                    <${WithdrawIcon} /> Withdraw this complaint
                  </button>`}
            </div>`}
        </section>`}
    <//>`;
}

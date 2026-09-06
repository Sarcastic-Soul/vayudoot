/* The Right to Information application, for a complaint that went unanswered.
 *
 * A separate citizen action, not a step inside escalation, and the panel is
 * shaped to say so. Escalation re-files the same complaint one tier up; this
 * asks the *original* authority's Public Information Officer what is written on
 * the file, and that question carries a statutory thirty-day duty to reply
 * which the complaint never had. So it sits in its own card, below the
 * escalation decision rather than inside it.
 *
 * Four states, and each is a different thing to say:
 *
 * - The clock is running but has not lapsed. The lever is named and dated
 *   rather than hidden, because a citizen should learn it exists before the day
 *   they need it. No control, since the server would answer 409.
 * - Lapsed, nothing drafted. One button, and an honest sentence about what
 *   pressing it costs: this is the only control in the interface that spends a
 *   primary-tier model call.
 * - Drafting. Tens of seconds of a model writing a legal document. A spinner
 *   that says nothing for forty seconds is indistinguishable from a hang, so
 *   this counts the seconds out loud and shows the shape of the document that
 *   is coming.
 * - Drafted. The document, what still has to be filled in, and a copy control.
 *
 * The placeholders are the point of the fourth state. An RTI application is
 * made by a named citizen with their own address and their own fee, none of
 * which this system knows or may invent — so the draft arrives with bracketed
 * gaps in it. That is the honest state of the document, not a defect to bury:
 * the gaps are highlighted in the text, counted in the header, and listed as a
 * checklist above it. A reader who copies this and files it without reading
 * has been failed by the interface, not by the draft.
 *
 * Nothing here sends anything. There is no transport, and the panel says so in
 * the same words the rendered document does.
 */

import { useEffect, useState } from "../vendor/hooks.mjs";
import { html, Fragment } from "../lib/html.js";
import { api } from "../lib/api.js";
import { onDate, inDays, rtiAvailable, rtiAvailableAt } from "../lib/format.js";
import { AskIcon, CopyIcon, CheckIcon, LockIcon } from "./Icons.js";

/* A bracketed gap a human has to close. Capped in length so the draft's own
   opening notice — one long bracketed sentence saying nothing has been filed —
   is not mistaken for a field to fill in. Single-line by construction: every
   real placeholder sits on one line of the rendered form. */
const FIELD = /\[[^\]\n]{1,90}\]/g;

/* The rendered application opens with that notice. It is shown as what it is —
   a standing statement about this whole product — rather than as the first
   paragraph of a legal document, and it stays in the copied text. */
const NOTICE = "[DRAFT";

function splitNotice(text) {
  const end = text.indexOf("\n");
  if (end < 0 || !text.startsWith(NOTICE)) return { notice: "", body: text };
  return { notice: text.slice(0, end).replace(/^\[|\]$/g, ""), body: text.slice(end + 1).trim() };
}

/* The document, with every bracketed gap marked. Built as an array of nodes
   rather than as markup, because the text is server data and there is no
   innerHTML anywhere in this interface. */
function marked(text) {
  const out = [];
  let last = 0;
  let match;
  FIELD.lastIndex = 0;
  while ((match = FIELD.exec(text)) !== null) {
    if (match.index > last) out.push(text.slice(last, match.index));
    out.push(html`<mark key=${match.index} class="fillin">${match[0]}</mark>`);
    last = match.index + match[0].length;
  }
  out.push(text.slice(last));
  return out;
}

function countFields(text) {
  FIELD.lastIndex = 0;
  return (text.match(FIELD) || []).length;
}

export function RTIPanel({ record, onUpdate }) {
  const [busy, setBusy] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [failure, setFailure] = useState("");
  const [text, setText] = useState("");
  const [copied, setCopied] = useState("");
  const [asking, setAsking] = useState(false);

  const drafted = record.rti;
  const draftedAt = record.rti_drafted_at || "";

  /* The filing-ready text comes from the endpoint that serves it, so what is
     copied is exactly what a person would get by fetching the document. The
     copy held on the case is identical and stands in if that call fails. */
  useEffect(() => {
    if (!drafted) { setText(""); return undefined; }
    let live = true;
    setText(drafted.body_en || "");
    api(`/cases/${record.case_id}/rti`)
      .then((body) => { if (live && typeof body === "string" && body) setText(body); })
      .catch(() => { /* the copy on the case is the same document */ });
    return () => { live = false; };
  }, [record.case_id, draftedAt]);

  /* Counting out loud. The only honest thing to show during a model call of
     unknown length is how long it has actually been going. */
  useEffect(() => {
    if (!busy) { setSeconds(0); return undefined; }
    const started = Date.now();
    const timer = setInterval(() => setSeconds(Math.round((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [busy]);

  async function draft(again) {
    setBusy(true);
    setFailure("");
    setCopied("");
    try {
      const url = `/cases/${record.case_id}/rti${again ? "?redraft=true" : ""}`;
      onUpdate(await api(url, { method: "POST" }));
      setAsking(false);
    } catch (error) {
      setFailure(error.message);
      /* A refusal means the case moved under this page — it was resolved or
         withdrawn elsewhere. Take the server's word for where it actually is. */
      if (error.status === 409) {
        try { onUpdate(await api(`/cases/${record.case_id}`)); } catch { /* keep what we have */ }
      }
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied("ok");
    } catch {
      setCopied("no");
    }
  }

  const available = rtiAvailable(record);
  const due = rtiAvailableAt(record);
  if (!drafted && !available && due === null) return null;

  const authority = (record.jurisdiction && record.jurisdiction.authority_name) || "the authority";
  const days = record.jurisdiction && record.jurisdiction.response_window_days;

  const head = html`
    <div class="rti-head">
      <${AskIcon} />
      <div>
        <p class="eyebrow">Right to Information Act, 2005</p>
        <h3>Ask what was actually done</h3>
      </div>
    </div>`;

  /* ── the clock is running, but has not lapsed ─────────────────────── */
  if (!drafted && !available) {
    return html`
      <section class="rti" aria-labelledby="rti-heading">
        ${head}
        <p class="rti-lead" id="rti-heading">
          If ${authority} never answers, a second complaint is not a lever — there was no duty
          to answer the first one. An application under the Right to Information Act is
          different in kind: it goes to a Public Information Officer, and section 7(1) gives
          them thirty days to reply.
        </p>
        <p class="rti-when">
          Available from <strong>${onDate(due)}</strong>, ${inDays(due)} — once the
          ${days ? `${days}-day ` : ""}window since filing has actually lapsed.
        </p>
      </section>`;
  }

  /* ── lapsed, nothing drafted ──────────────────────────────────────── */
  if (!drafted) {
    return html`
      <section class="rti is-open" aria-labelledby="rti-heading">
        ${head}
        <p class="rti-lead" id="rti-heading">
          The ${days ? `${days}-day ` : ""}window has lapsed and ${authority} has not answered.
          An RTI application asks that office what is written on the file about this complaint,
          and section 7(1) obliges it to reply within thirty days — which the complaint itself
          never did.
        </p>
        ${busy ? html`<${Drafting} seconds=${seconds} />` : html`
          <${Fragment}>
            <button type="button" class="primary" onClick=${() => draft(false)}>
              <${AskIcon} /> Draft the application
            </button>
            <p class="help">
              <${LockIcon} />
              <span>This writes the document with a language model, which takes tens of
                seconds rather than the usual instant. It is drafted once and kept on the
                case. Nothing is sent: you file it yourself, in your own name.</span>
            </p>
          <//>`}
        ${failure && html`
          <p class="error" role="alert">
            <strong>That did not go through.</strong> ${failure}
          </p>`}
      </section>`;
  }

  /* ── drafted ──────────────────────────────────────────────────────── */
  const { notice, body } = splitNotice(text);
  const gaps = countFields(body);
  const items = drafted.placeholders || [];

  return html`
    <section class="rti is-open" aria-labelledby="rti-heading">
      ${head}
      <p class="rti-lead" id="rti-heading">${drafted.subject}</p>

      ${notice && html`
        <p class="rti-notice"><${LockIcon} /><span>${notice}</span></p>`}

      ${(items.length > 0 || gaps > 0) && html`
        <div class="rti-todo">
          <p class="rti-todo-head">
            <strong>To be completed before filing</strong>
            ${gaps > 0 && html`
              <span class="rti-count tnum">
                ${gaps} bracketed ${gaps === 1 ? "field" : "fields"} in the text
              </span>`}
          </p>
          ${items.length > 0
            ? html`
              <ul class="rti-todo-list">
                ${items.map((item, i) => html`<li key=${i}>${item}</li>`)}
              </ul>`
            : html`
              <p class="rti-todo-note">Every bracketed field highlighted below is yours to
                fill in — your name, your address, and the fee.</p>`}
        </div>`}

      ${body
        ? html`
          <${Fragment}>
            <div class="rti-doc-head">
              <p class="section-label">The application</p>
              <button type="button" class="secondary rti-copy" onClick=${copy}>
                ${copied === "ok"
                  ? html`<${CheckIcon} /> Copied`
                  : html`<${CopyIcon} /> Copy the whole application`}
              </button>
            </div>
            ${copied === "no" && html`
              <p class="help" role="alert">This browser would not let the page reach the
                clipboard. Select the text below and copy it yourself.</p>`}
            <pre class="rti-doc">${marked(body)}</pre>
          <//>`
        /* The drafting agent produced a structured application but no rendered
           text — the questions are on the case, the document is not. Say that
           rather than showing an empty box that looks like a failed load. */
        : html`
          <p class="error" role="alert">
            <strong>This draft has no rendered text.</strong> The application was drafted but
            the filing-ready document did not come back with it. Draft it again below.
          </p>`}

      ${drafted.questions && drafted.questions.length > 0 && html`
        <p class="rti-foot">
          ${drafted.questions.length} ${drafted.questions.length === 1 ? "question" : "questions"},
          asking only for information already held on a file. An RTI that demands action rather
          than information is refused, and thirty days are lost.
        </p>`}

      <p class="rti-drafted tnum">
        Drafted ${onDate(record.rti_drafted_at)}. Nothing has been sent.
      </p>

      ${busy ? html`<${Drafting} seconds=${seconds} again=${true} />` : html`
        <div class="rti-redraft">
          ${asking
            ? html`
              <div class="update-panel">
                <p class="decision">
                  Redrafting throws this document away and writes another one, which is a
                  second model call. Worth it if the case has moved since — an acknowledgement
                  recorded, or an escalation — and not otherwise.
                </p>
                <div class="panel-buttons">
                  <button type="button" class="primary" onClick=${() => draft(true)}>
                    Draft it again
                  </button>
                  <button type="button" class="quiet" onClick=${() => setAsking(false)}>
                    Keep this draft
                  </button>
                </div>
              </div>`
            : html`
              <button type="button" class="quiet" onClick=${() => setAsking(true)}>
                Draft it again
              </button>`}
        </div>`}

      ${failure && html`
        <p class="error" role="alert">
          <strong>That did not go through.</strong> ${failure}
        </p>`}
    </section>`;
}

/* The wait, shown rather than hidden. A live count of seconds, the shape of
   the document that is coming, and one sentence saying why it is slow. */
function Drafting({ seconds, again }) {
  return html`
    <div class="rti-working" aria-busy="true">
      <p class="rti-working-head" role="status" aria-live="polite">
        <span class="rti-dot" aria-hidden="true"></span>
        ${again ? "Redrafting" : "Drafting"} the application…
        <span class="tnum">${seconds}s</span>
      </p>
      <p class="rti-working-note">
        One model call, writing a legal document from scratch. Tens of seconds is normal.
      </p>
      <div class="rti-doc-skeleton" aria-hidden="true">
        ${[0, 1, 2, 3, 4, 5].map((i) => html`<span key=${i} class="skeleton"></span>`)}
      </div>
    </div>`;
}

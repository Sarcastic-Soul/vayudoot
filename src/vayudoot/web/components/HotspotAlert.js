/* Alerting the authority about a hotspot: the sibling of filing a complaint.
 *
 * Until alerts existed, a fire that satellites and a station agreed on — with
 * no citizen standing near it — reached nobody. This is the route by which it
 * does, and it is built to feel like `Complaint` + `CaseActions` on purpose: a
 * drafted document the operator reads in full, then one decision block, in the
 * accent green, that says exactly what pressing it does.
 *
 * Three rules shape it, all enforced by the server and mirrored here so a
 * control that would be refused is not drawn:
 *
 * - **Only a corroborated hotspot can be alerted** (hard constraint 7). An
 *   alert is a claim made in this system's name. An uncorroborated hotspot
 *   gets an explanation rather than a dead button: what is missing, and that
 *   the citizens behind it already have their own route — a complaint. The
 *   longer reason sits behind a "Why?" disclosure.
 * - **Nothing is sent before a person confirms** (hard constraint 2). Drafting
 *   stops at `awaiting_confirmation`; only "Confirm and send" writes anything,
 *   and what it writes goes to the sandbox outbox to a `.invalid` address
 *   (hard constraint 1). The sent state shows the envelope exactly as written,
 *   labelled SANDBOX, so nobody can mistake it for a delivered letter.
 * - **The facts are code; only the summary is the model's.** The review panel
 *   keeps the two visibly apart — the model-written brief under the model
 *   mark, the Python-built facts block verbatim in monospace.
 *
 * On load it asks for an alert this hotspot already has, so a pending draft is
 * shown rather than paid for twice, and a sent one is shown as sent.
 */

import { useEffect, useState } from "../vendor/hooks.mjs";
import { html, Fragment } from "../lib/html.js";
import { api, apiUrl } from "../lib/api.js";
import { navigate } from "../lib/router.js";
import { onDate, atTime, words } from "../lib/format.js";
import {
  AlertMailIcon, CameraIcon, CheckIcon, FeedIcon, LockIcon, ModelIcon, RetryIcon, SendIcon,
  UnverifiedIcon,
} from "./Icons.js";

/* Seconds since a moment, ticking. The only progress an honest slow call has. */
export function Elapsed({ since }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const secs = Math.max(0, Math.round((now - (since || now)) / 1000));
  return html`<span class="tnum">${secs} s</span>`;
}

const COVERAGE = {
  exact: "Named for this area in the authority table",
  fallback: "One tier up — the local body is not in the table",
  generic: "Placeholder — this region is not in the table",
};

const whenSent = (iso) => {
  const at = Date.parse(iso);
  return Number.isNaN(at) ? "" : `${onDate(iso)}, ${atTime(at)}`;
};

/* ── the uncorroborated case ─────────────────────────────────────────── */

function NotAlertable({ hotspot }) {
  return html`
    <section class="alert-card is-blocked" aria-labelledby="alert-heading">
      <div class="alert-card-head">
        <span class="alert-glyph is-muted" aria-hidden="true"><${UnverifiedIcon} /></span>
        <div>
          <p class="eyebrow">Alert the authority</p>
          <h3 id="alert-heading">Not available for this hotspot</h3>
        </div>
      </div>
      <p class="alert-why">Needs a satellite or station reading that agrees.</p>
      <details class="why">
        <summary>Why?</summary>
        <p>An alert is a claim this system makes <em>in its own name</em>. A map that turned
          citizen reports alone into official alerts could be steered by anyone who filed
          enough of them.</p>
      </details>
      <ul class="alert-routes">
        <li>
          <${CameraIcon} />
          <span><strong>Reporters can file their own complaint</strong>${
            hotspot.case_ids.length ? " — cases listed above" : ""}.</span>
        </li>
        <li>
          <${AlertMailIcon} />
          <span><strong>Unlocks by itself</strong> once independent evidence agrees.</span>
        </li>
      </ul>
      <button type="button" class="secondary" onClick=${() => navigate("report")}>
        <${CameraIcon} /> Report what you can see
      </button>
    </section>`;
}

/* ── the draft, for review ──────────────────────────────────────────── */

function Brief({ brief }) {
  const [lang, setLang] = useState("en");
  const hasLocal = Boolean(brief.summary_local && brief.summary_local.trim());
  const showing = hasLocal && lang === "local" ? "local" : "en";
  return html`
    <div class="alert-brief">
      <div class="alert-brief-bar">
        <span class="model-mark"><${ModelIcon} />Summary written by a model</span>
        ${hasLocal && html`
          <div class="lang-toggle" role="group" aria-label="Summary language">
            <button type="button" class=${showing === "en" ? "is-active" : ""}
                    aria-pressed=${showing === "en"} onClick=${() => setLang("en")}>
              English</button>
            <button type="button" class=${showing === "local" ? "is-active" : ""}
                    aria-pressed=${showing === "local"} onClick=${() => setLang("local")}>
              ${brief.local_language || "Local language"}</button>
          </div>`}
      </div>
      <p class="alert-summary" lang=${showing === "local" ? "" : "en"}>
        ${showing === "local" ? brief.summary_local : brief.summary_en}
      </p>
      ${hasLocal && html`
        <p class="alert-lang-note">
          Also sent in ${brief.local_language || "the region's language"}.
        </p>`}
      ${brief.suggested_checks && brief.suggested_checks.length > 0 && html`
        <${Fragment}>
          <h4 class="section-label">Suggested checks for an inspector</h4>
          <ol class="alert-checks">
            ${brief.suggested_checks.map((check, i) => html`<li key=${i}>${check}</li>`)}
          </ol>
        <//>`}
    </div>`;
}

function Route({ alert }) {
  const j = alert.jurisdiction;
  return html`
    <dl class="alert-route">
      <div class="is-to">
        <dt>To</dt>
        <dd>
          <strong>${j.authority_name}</strong>
          <span class="alert-tier">${j.authority_tier}</span>
          ${j.office && html`<span class="alert-office">${j.office}</span>`}
          <span class="alert-address">
            <code>${j.email || "no address on file"}</code>
            <span class="sandbox-tag" title="The reserved .invalid domain can never deliver">
              <${LockIcon} />sandbox address</span>
          </span>
        </dd>
      </div>
      <div>
        <dt>Under</dt>
        <dd>${j.statute}${j.section ? html`<span class="alert-section">${j.section}</span>` : ""}</dd>
      </div>
      <div>
        <dt>Area</dt>
        <dd>${alert.area || "Area name unavailable"}
          <span class="alert-section">${alert.hotspot.radius_km.toFixed(1)} km radius — an
            area, not any one site</span></dd>
      </div>
      <div class=${`is-coverage is-${j.coverage}`}>
        <dt>Match</dt>
        <dd>${COVERAGE[j.coverage] || words(j.coverage)}
          ${j.coverage_note && html`<span class="alert-section">${j.coverage_note}</span>`}</dd>
      </div>
    </dl>`;
}

function ImageryNote({ imagery }) {
  if (!imagery) return null;
  return html`
    <p class="alert-imagery">
      <span class="model-mark"><${ModelIcon} />Imagery reading cited</span>
      <span>${imagery.image_date}: plume ${imagery.plume_visible ? "visible" : "not visible"},
        cloud ${imagery.cloud_obscured ? "over the area" : "clear"}. Context only, not
        corroboration.</span>
    </p>`;
}

function Draft({ alert }) {
  return html`
    <article class="alert-doc" aria-labelledby="alert-subject">
      <div class="alert-doc-head">
        <p class="eyebrow">Alert drafted for your review</p>
        <h3 id="alert-subject">${alert.brief ? alert.brief.subject : `Hotspot ${alert.hotspot_id}`}</h3>
        <p class="alert-ref tnum">${alert.alert_id} · drafted ${whenSent(alert.created_at)}</p>
      </div>
      <${Route} alert=${alert} />
      ${alert.brief && html`<${Brief} brief=${alert.brief} />`}
      <${ImageryNote} imagery=${alert.imagery} />
      <details class="alert-facts" open>
        <summary>
          <span>Facts block</span>
          <span class="facts-tag">built by code, not the model</span>
        </summary>
        <pre>${alert.facts}</pre>
      </details>
    </article>`;
}

/* ── the flow ────────────────────────────────────────────────────────── */

export function HotspotAlert({ hotspot, onAlert }) {
  const id = hotspot.hotspot_id;
  const [alert, setAlert] = useState(undefined);   // undefined: still asking
  const [busy, setBusy] = useState("");            // "draft" | "send"
  const [startedAt, setStartedAt] = useState(0);
  const [failure, setFailure] = useState(null);
  const [envelope, setEnvelope] = useState("");

  useEffect(() => {
    if (!hotspot.corroborated) return undefined;
    let live = true;
    api(`/alerts?hotspot_id=${encodeURIComponent(id)}`)
      .then((found) => {
        if (!live) return;
        const list = Array.isArray(found) ? found : [];
        // A pending draft is the thing to act on; otherwise the newest sent one.
        setAlert(list.find((a) => a.status === "awaiting_confirmation") || list[0] || null);
      })
      .catch(() => { if (live) setAlert(null); });
    return () => { live = false; };
  }, [id, hotspot.corroborated]);

  const sent = alert && alert.status === "sent";

  useEffect(() => {
    if (!sent) { setEnvelope(""); return undefined; }
    let live = true;
    api(`/alerts/${encodeURIComponent(alert.alert_id)}/envelope`)
      .then((text) => { if (live) setEnvelope(text); })
      .catch((e) => { if (live) setEnvelope(`(The envelope could not be read: ${e.message})`); });
    return () => { live = false; };
  }, [sent, alert && alert.alert_id]);

  useEffect(() => { if (onAlert && alert !== undefined) onAlert(alert); }, [alert]);

  if (!hotspot.corroborated) return html`<${NotAlertable} hotspot=${hotspot} />`;

  async function draft() {
    setBusy("draft");
    setStartedAt(Date.now());
    setFailure(null);
    try {
      setAlert(await api(`/hotspots/${encodeURIComponent(id)}/alert`, { method: "POST" }));
    } catch (error) {
      setFailure({ status: error.status, message: error.message, what: "draft" });
    } finally {
      setBusy("");
    }
  }

  async function send() {
    setBusy("send");
    setFailure(null);
    try {
      setAlert(await api(`/alerts/${encodeURIComponent(alert.alert_id)}/confirm`,
        { method: "POST" }));
    } catch (error) {
      setFailure({ status: error.status, message: error.message, what: "send" });
      // A 409 means the alert moved under us; take the server's word for it.
      if (error.status === 409) {
        try { setAlert(await api(`/alerts/${encodeURIComponent(alert.alert_id)}`)); } catch {
          /* keep what we have */
        }
      }
    } finally {
      setBusy("");
    }
  }

  const problem = failure && html`<${AlertFailure} failure=${failure}
    onRetry=${failure.what === "send" ? send : draft} />`;

  /* Still asking whether an alert exists. */
  if (alert === undefined) {
    return html`
      <section class="alert-card" aria-busy="true">
        <p class="visually-hidden" role="status">Checking for an existing alert.</p>
        <div class="skeleton" style="height:18px;width:40%"></div>
        <div class="skeleton" style="height:52px;margin-top:12px"></div>
      </section>`;
  }

  /* Sent: the envelope, exactly as the sandbox outbox holds it. */
  if (sent) {
    return html`
      <section class="alert-card is-sent" aria-labelledby="alert-heading">
        <div class="alert-card-head">
          <span class="alert-glyph is-ok" aria-hidden="true"><${CheckIcon} /></span>
          <div>
            <p class="eyebrow">Alert the authority</p>
            <h3 id="alert-heading">Alert sent to the sandbox outbox</h3>
          </div>
        </div>
        <p class="alert-why">
          ${whenSent(alert.sent_at)} · to <strong>${alert.jurisdiction.authority_name}</strong>
          ${" "}at a <code>.invalid</code> address — written to the outbox, delivered nowhere.
        </p>
        <div class="envelope-sandbox">
          <div class="envelope-bar">
            <span class="sandbox-flag"><${LockIcon} />Sandbox</span>
            <span>Envelope as written to the outbox · <span class="tnum">${alert.alert_id}</span></span>
          </div>
          <pre class="envelope-text">${envelope || "Reading the outbox…"}</pre>
        </div>
      </section>`;
  }

  /* Drafted, waiting for a person. */
  if (alert && alert.status === "awaiting_confirmation") {
    return html`
      <section class="alert-flow" aria-label="Alert to the authority">
        <${Draft} alert=${alert} />
        <div class="actions alert-decision">
          <p class="eyebrow">Your decision</p>
          <p class="decision">
            Sends exactly what is shown above to ${alert.jurisdiction.authority_name}.
            Nothing has gone anywhere yet.
          </p>
          <button type="button" class="primary" disabled=${Boolean(busy)} onClick=${send}>
            ${busy === "send" ? "Sending…" : html`<${SendIcon} /> Confirm and send this alert`}
          </button>
          <p class="help">
            <${LockIcon} />
            <span>Sandbox outbox, <code>.invalid</code> address. No authority is
              contacted.</span>
          </p>
          ${problem}
        </div>
      </section>`;
  }

  /* Nothing yet: offer to draft one. */
  return html`
    <section class="alert-card is-ready" aria-labelledby="alert-heading">
      <div class="alert-card-head">
        <span class="alert-glyph" aria-hidden="true"><${AlertMailIcon} /></span>
        <div>
          <p class="eyebrow">Alert the authority</p>
          <h3 id="alert-heading">Tell the office that covers this area</h3>
        </div>
      </div>
      <ul class="alert-steps" aria-label="What drafting does">
        <li><${CheckIcon} />Authority from the table</li>
        <li><${CheckIcon} />Facts from the data</li>
        <li><${ModelIcon} />Summary by a model</li>
      </ul>
      <p class="alert-why alert-promise">
        <${LockIcon} /><span><strong>Nothing is sent</strong> — you read the draft first.</span>
      </p>
      ${busy === "draft"
        ? html`
          <div class="alert-pending" aria-busy="true">
            <p class="visually-hidden" role="status">Drafting the alert. This takes a few
              seconds.</p>
            <span class="pending-spark" aria-hidden="true"><${ModelIcon} /></span>
            <ol>
              <li>Resolving the authority from the table — no model</li>
              <li>Building the facts block from the hotspot — no model</li>
              <li>Writing the summary — one fast-tier model call</li>
            </ol>
            <span class="pending-clock" aria-hidden="true"><${Elapsed} since=${startedAt} /></span>
          </div>`
        /* A refusal on jurisdiction is an answer, not a fault: asking again gets the
           same one, so the button goes and the refusal stands in its place. */
        : failure && failure.status === 422 ? null : html`
          <button type="button" class="primary" onClick=${draft}>
            <${AlertMailIcon} /> Draft alert to authority
          </button>`}
      ${problem}
    </section>`;
}

/* The server's own sentence, with the part it cannot know: what to do next. */
function AlertFailure({ failure, onRetry }) {
  const { status, message } = failure;
  const busy = status === 503 || status === 429;
  const abroad = status === 422;
  const stale = status === 409;
  const hint = abroad
    ? "Nothing was drafted and no model was asked. The hotspot stays on this node's map "
      + "and in its feed."
    : busy
      ? "The free-tier model is busy or over its quota. Nothing was saved; trying again in a "
        + "minute usually works."
      : stale
        ? "The hotspot or the alert changed while this page was open. What is shown now is "
          + "the server's current state."
        : status === 502
          ? "The area could not be placed, so there is no honest answer to who to send it to. "
            + "Nothing was saved."
          : "Nothing was saved.";
  return html`
    <div class=${`alert-failure${abroad || busy ? " is-limit" : ""}`} role="alert">
      <p><strong>${abroad ? "Outside this node's jurisdiction." : busy
        ? "The model could not answer right now." : "That did not go through."}</strong>
        ${" "}${message}</p>
      <p class="alert-failure-hint">${hint}</p>
      <div class="alert-failure-actions">
        ${abroad && html`
          <a class="secondary-link" href=${apiUrl("/feed.geojson")} target="_blank" rel="noopener">
            <${FeedIcon} /> Open the federation feed</a>`}
        ${(busy || status === 502 || !status) && html`
          <button type="button" class="secondary" onClick=${onRetry}>
            <${RetryIcon} /> Try again
          </button>`}
      </div>
    </div>`;
}

/* One corridor's outlook: waiting for it, failing to get it, and reading it.
 *
 * **Hard constraint 7 is the whole shape of this file.** A forecast is a model's
 * reasoning over public data, people act on air quality predictions, and an
 * unlabelled wrong one does real harm to real lungs. So every rendering of an
 * outlook carries three things in plain sight, never behind a click: the
 * `disclaimer` the server attached, verbatim; the inputs the model read
 * (`basis`); and how sure it says it is. The words are conditions — "the model
 * expects conditions that let pollution build up" — and never instructions. No
 * seal, no crest, no red "ALERT" banner, nothing an official advisory would
 * wear: the model-derived mark is a small spark in the information colour, and
 * it is on every panel that says anything predictive.
 *
 * The waiting state is honest about why it is slow. One model call per
 * waypoint, all in parallel, on a free tier: there is no progress to report
 * between "asked" and "answered", so the page shows a clock and says what it is
 * waiting for rather than drawing a progress bar it would have to invent.
 *
 * Worst first. The corridor carries the worst band any waypoint carries, and
 * the list under it opens on the waypoint that set it, because the segment in
 * trouble is the thing an authority needs to see.
 */

import { useEffect, useState } from "../vendor/hooks.mjs";
import { html, Fragment } from "../lib/html.js";
import {
  RISK_BLURB, worstFirst, waypointIndex, waypointName, coordLabel,
  peakWindow, confidenceRange, basisOf, percent, shortWhen, plural, riskRank,
} from "../lib/format.js";
import { ModelIcon, RetryIcon, FailedIcon } from "./Icons.js";

export function ModelMark({ children = "Model-derived outlook" }) {
  return html`<span class="model-mark"><${ModelIcon} />${children}</span>`;
}

export function RiskChip({ risk, suffix = "" }) {
  return html`
    <span class="risk-chip" data-risk=${risk}>
      <span class="risk-dot" aria-hidden="true"></span>${risk}${suffix}
    </span>`;
}

/* The disclaimer, verbatim from the object. Not paraphrased: the wording is
   fixed server-side so every surface that shows a forecast says the same thing. */
export function Disclaimer({ text, compact = false }) {
  if (!text) return null;
  return html`
    <aside class=${`disclaimer${compact ? " is-compact" : ""}`}>
      <${ModelIcon} />
      <div>
        ${!compact && html`<strong>A model's reasoning, not an official forecast</strong>`}
        <p>${text}</p>
      </div>
    </aside>`;
}

/* ── waiting ─────────────────────────────────────────────────────────── */

function Elapsed({ since }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const secs = Math.max(0, Math.round((now - (since || now)) / 1000));
  return html`<span class="tnum">${secs} s</span>`;
}

export function OutlookPending({ corridor, startedAt }) {
  const n = corridor.waypoints.length;
  return html`
    <div class="outlook-pending" aria-busy="true">
      <p class="visually-hidden" role="status">
        Asking the model about ${n} waypoints. This usually takes under a minute.</p>
      <div class="pending-head">
        <span class="pending-spark" aria-hidden="true"><${ModelIcon} /></span>
        <div>
          <h3>Asking the model about ${n} waypoints…</h3>
          <p>One call per sampling point, all in parallel, on a free tier. This usually takes
            20 to 60 seconds; the answer is then kept for 30 minutes.</p>
        </div>
        <span class="pending-clock" aria-hidden="true"><${Elapsed} since=${startedAt} /></span>
      </div>
      <ol class="pending-list" aria-hidden="true">
        ${corridor.waypoints.map(([lat, lon], i) => html`
          <li key=${i}>
            <span class="wp-num">${i + 1}</span>
            <span class="tnum">${coordLabel(lat, lon)}</span>
            <span class="skeleton"></span>
          </li>`)}
      </ol>
      <p class="pending-note">Each waypoint reads a pollutant forecast, a wind forecast and every
        hotspot within reach upwind — this node's own and its neighbours'.</p>
    </div>`;
}

/* ── failing ─────────────────────────────────────────────────────────── */

export function OutlookFailed({ error, status, onRetry }) {
  const quota = status === 429 || /quota|rate|exhaust|limit/i.test(error || "");
  return html`
    <div class="outlook-failed" role="alert">
      <${FailedIcon} />
      <div>
        <h3>The outlook could not be produced</h3>
        <p class="failed-detail">${error || "The server gave no reason."}</p>
        <p class="failed-hint">
          ${quota
            ? "The free-tier model quota looks spent for now. It refills on its own; nothing is "
              + "cached after a failure, so retrying asks again."
            : "Nothing is cached after a failure, so retrying asks the model again."}
        </p>
        <button type="button" class="secondary" onClick=${onRetry}>
          <${RetryIcon} /> Try again
        </button>
      </div>
    </div>`;
}

/* ── reading ─────────────────────────────────────────────────────────── */

/* The corridor as a strip, first waypoint to last, one cell per waypoint in its
   band. A waypoint whose call failed is drawn hatched and said to be missing —
   it is not low risk, it is unknown. */
function Ribbon({ corridor, byIndex, focus, onFocus }) {
  const n = corridor.waypoints.length;
  const first = byIndex.get(0);
  const last = byIndex.get(n - 1);
  return html`
    <div class="ribbon-wrap">
      <ol class="ribbon" aria-label="Outlook at each waypoint, in corridor order">
        ${corridor.waypoints.map((_, i) => {
          const f = byIndex.get(i);
          return html`
            <li key=${i}>
              <button type="button" class=${`ribbon-cell${focus === i ? " is-focus" : ""}`}
                      data-risk=${f?.risk || "none"}
                      aria-label=${`Waypoint ${i + 1}: ${f ? `${f.risk} risk` : "no answer"}`}
                      onClick=${() => onFocus(i)}>
                <span class="tnum">${i + 1}</span>
              </button>
            </li>`;
        })}
      </ol>
      <div class="ribbon-ends">
        <span>${first ? waypointName(first, corridor, 0) : "Waypoint 1"}</span>
        <span>${last ? waypointName(last, corridor, n - 1) : `Waypoint ${n}`}</span>
      </div>
    </div>`;
}

function Bullets({ items, className }) {
  if (!items?.length) return null;
  return html`
    <ul class=${className}>${items.map((item, i) => html`<li key=${i}>${item}</li>`)}</ul>`;
}

function WaypointOutlook({ forecast, corridor, index, worst, open, corridorDisclaimer,
  onToggle }) {
  const peak = peakWindow(forecast.peak_window_start, forecast.peak_window_end);
  return html`
    <li id=${`wp-${index}`}>
      <details class="wp-card" data-risk=${forecast.risk} open=${open}
               onToggle=${(e) => onToggle(index, e.currentTarget.open)}>
        <summary>
          <span class="wp-num" data-risk=${forecast.risk}>${index >= 0 ? index + 1 : "?"}</span>
          <span class="wp-head">
            <span class="wp-name">
              ${waypointName(forecast, corridor, index)}
              ${worst && html`<span class="worst-tag">Worst segment</span>`}
            </span>
            <span class="wp-where tnum">${coordLabel(forecast.latitude, forecast.longitude)}</span>
          </span>
          <span class="wp-figs">
            <${RiskChip} risk=${forecast.risk} />
            <span class="wp-conf tnum" title="How sure the model says it is">
              ${percent(forecast.confidence)}<small>confidence</small></span>
          </span>
        </summary>

        <div class="wp-body">
          <p class="wp-blurb">${RISK_BLURB[forecast.risk]}</p>
          <dl class="wp-facts">
            <div>
              <dt>Peak window</dt>
              <dd>${peak || html`<span class="muted">The model did not name one</span>`}</dd>
            </div>
            <div>
              <dt>Looks ahead</dt>
              <dd class="tnum">${forecast.horizon_hours} hours</dd>
            </div>
            <div>
              <dt>Confidence</dt>
              <dd>
                <span class="tnum">${percent(forecast.confidence)}</span>
                <span class="conf-meter" aria-hidden="true">
                  <span style=${`width:${Math.round(forecast.confidence * 100)}%`}></span>
                </span>
              </dd>
            </div>
          </dl>

          ${forecast.drivers?.length > 0 && html`
            <h4 class="eyebrow">Conditions driving it</h4>
            <${Bullets} items=${forecast.drivers} className="drivers" />`}

          ${forecast.reasoning && html`
            <h4 class="eyebrow">The model's reasoning</h4>
            <p class="wp-reasoning">${forecast.reasoning}</p>`}

          <h4 class="eyebrow">Inputs it read</h4>
          ${forecast.basis?.length
            ? html`<${Bullets} items=${forecast.basis} className="basis" />`
            : html`<p class="muted wp-none">The model listed no inputs for this waypoint, so
                there is nothing to check its work against. Read it as unsupported.</p>`}

          ${forecast.disclaimer && forecast.disclaimer !== corridorDisclaimer
            && html`<${Disclaimer} text=${forecast.disclaimer} compact />`}
        </div>
      </details>
    </li>`;
}

export function OutlookResult({ corridor, forecast, focus, onFocus }) {
  const answered = forecast.waypoint_forecasts || [];
  const ordered = worstFirst(answered);
  // The worst waypoint opens by itself; every other card waits to be asked.
  const [opened, setOpened] = useState(() => new Set(
    ordered.length ? [waypointIndex(corridor, ordered[0])] : []));
  const byIndex = new Map();
  for (const f of answered) {
    const i = waypointIndex(corridor, f);
    if (i >= 0) byIndex.set(i, f);
  }
  const missing = corridor.waypoints.length - byIndex.size;
  const worstIndex = ordered.length ? waypointIndex(corridor, ordered[0]) : -1;
  const confidence = confidenceRange(answered);
  const inputs = basisOf(answered);

  // The ribbon and the map both pick a waypoint; open its card and bring it
  // into view, so a tap on the map ends on the text that explains the colour.
  useEffect(() => {
    if (focus == null || focus < 0) return;
    setOpened((was) => new Set(was).add(focus));
    const card = document.getElementById(`wp-${focus}`);
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    card?.scrollIntoView({ behavior: still ? "auto" : "smooth", block: "nearest" });
  }, [focus]);

  const toggle = (i, isOpen) => setOpened((was) => {
    const next = new Set(was);
    if (isOpen) next.add(i); else next.delete(i);
    return next;
  });

  if (!answered.length) {
    // The server defaults an empty corridor to "low". Showing that would turn
    // "no waypoint answered" into "all clear", which is the one reading this
    // must never allow.
    return html`
      <${Fragment}>
        <div class="outlook-failed" role="alert">
          <${FailedIcon} />
          <div>
            <h3>No waypoint produced an outlook</h3>
            <p class="failed-hint">Every call along this corridor failed, so there is no risk band
              to show — this is not a low-risk answer, it is no answer. The server may keep
              this empty result for up to 30 minutes before it asks the model again.</p>
          </div>
        </div>
        <${Disclaimer} text=${forecast.disclaimer} />
      <//>`;
  }

  return html`
    <${Fragment}>
      <section class="outlook-hero" data-risk=${forecast.risk} aria-labelledby="outlook-band">
        <div class="hero-top">
          <${ModelMark} />
          <span class="hero-when">Generated ${shortWhen(forecast.generated_at)}</span>
        </div>
        <div class="hero-main">
          <div class="hero-band">
            <span class="eyebrow">Worst along the corridor</span>
            <span class="hero-risk" id="outlook-band">${forecast.risk}<small> risk</small></span>
            <p>${RISK_BLURB[forecast.risk]}</p>
          </div>
          <dl class="hero-figs">
            <div>
              <dt>Confidence</dt>
              <dd class="tnum">${confidence || "—"}</dd>
              <dd class="hero-sub">the model's own, per waypoint</dd>
            </div>
            <div>
              <dt>Answered</dt>
              <dd class="tnum">${byIndex.size}/${corridor.waypoints.length}</dd>
              <dd class="hero-sub">${missing ? `${plural(missing, "waypoint")} failed`
                : "every waypoint"}</dd>
            </div>
            <div>
              <dt>Looks ahead</dt>
              <dd class="tnum">${Math.max(...answered.map((f) => f.horizon_hours || 0))} h</dd>
            </div>
          </dl>
        </div>
        ${forecast.summary && html`<p class="hero-summary">${forecast.summary}</p>`}
      </section>

      <${Disclaimer} text=${forecast.disclaimer} />

      ${missing > 0 && html`
        <p class="note is-limit">
          <strong>${plural(missing, "waypoint")} did not answer.</strong> ${" "}The corridor's band
          is the worst of those that did; a missing waypoint is unknown, not low.
        </p>`}

      <h3 class="section-label">Along the corridor</h3>
      <${Ribbon} corridor=${corridor} byIndex=${byIndex} focus=${focus} onFocus=${onFocus} />

      <div class="timeline-head wp-list-head">
        <h3 class="section-label" id="wp-list-label">Worst segment first</h3>
        <p class="timeline-progress">${plural(answered.length, "waypoint")}</p>
      </div>
      <ul class="wp-list" aria-labelledby="wp-list-label">
        ${ordered.map((f, rank) => {
          const i = waypointIndex(corridor, f);
          return html`
            <${WaypointOutlook} key=${`${f.latitude},${f.longitude}`} forecast=${f}
              corridor=${corridor} index=${i}
              worst=${rank === 0 && riskRank(f.risk) > 0}
              open=${opened.has(i)} corridorDisclaimer=${forecast.disclaimer}
              onToggle=${toggle} />`;
        })}
      </ul>

      ${inputs.length > 0 && html`
        <details class="inputs-all">
          <summary>Everything the model read along this corridor${" "}
            <span class="tnum">(${inputs.length})</span></summary>
          <${Bullets} items=${inputs} className="basis" />
        </details>`}

      <p class="outlook-foot">Band chosen as the worst waypoint, not an average: a corridor is
        a population strip and a supply line, and the segment in trouble is the one to see.
        ${worstIndex >= 0 && ` Here that is waypoint ${worstIndex + 1}.`}</p>
    <//>`;
}

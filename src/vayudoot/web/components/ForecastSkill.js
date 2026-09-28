/* How good the forecasts have been.
 *
 * Every outlook the node makes is written to a ledger before its window
 * opens, and scored once the window has closed against what reference
 * stations measured. This panel shows that record, and it is built around
 * three rules that keep it honest:
 *
 *   The sample size is the headline. Fourteen scored forecasts and fourteen
 *   hundred are different claims, so the count sits above every rate, and
 *   below the ledger's own threshold the panel says the rates are anecdote.
 *
 *   A rate is always beside its baselines. "57% exact" means nothing alone;
 *   it means something next to what carrying yesterday forward, or the raw
 *   CAMS forecast, would have scored on the same forecasts. Each comparison
 *   uses the subset both could be scored on, which is why the counts differ.
 *
 *   Nothing scored is not 0%. With no scored forecast the panel says so and
 *   shows no rate at all; a null rate reads as a dash, never as a number.
 *
 * The rates describe a model's reasoning, so the panel carries the same
 * "Model-derived" mark as every other predictive surface (hard constraint 7).
 * The server's caveat is shown verbatim rather than paraphrased.
 */

import { useState } from "../vendor/hooks.mjs";
import { html } from "../lib/html.js";
import { useForecastSkill } from "../lib/store.js";
import { capital, inDays, plural, rateText, shortWhen, SMALL_SAMPLE } from "../lib/format.js";
import { ModelMark, RiskChip } from "./CorridorOutlook.js";
import { TargetIcon, PendingIcon } from "./Icons.js";

const BANDS = ["low", "elevated", "high", "severe"];

const BASELINE_NAME = { persistence: "Persistence", cams: "Raw CAMS" };
const BASELINE_PHRASE = { persistence: "persistence", cams: "the raw CAMS forecast" };
const BASELINE_HEAD = { persistence: "Against persistence", cams: "Against the raw CAMS forecast" };

const pct = (rate) => (typeof rate === "number" && Number.isFinite(rate)
  ? Math.max(0, Math.min(100, rate * 100)) : 0);

/* One labelled bar. The width is the rate; a missing rate draws no bar and
   the text says a dash. */
function Bar({ label, rate, count, of, kind }) {
  return html`
    <div class=${`skill-bar is-${kind}`}>
      <span class="skill-bar-label">${label}</span>
      <span class="skill-bar-track" aria-hidden="true">
        <span class="skill-bar-fill" style=${`width:${pct(rate)}%`}></span>
      </span>
      <span class="skill-bar-value tnum">
        ${rateText(rate)}${of ? html`<small> ${count} of ${of}</small>` : null}
      </span>
    </div>`;
}

function Versus({ baseline }) {
  const name = BASELINE_NAME[baseline.name] || baseline.name;
  const { forecast: ours, baseline: theirs, compared } = baseline;
  if (!compared) {
    return html`
      <li class="skill-vs is-empty">
        <h4>${BASELINE_HEAD[baseline.name] || `Against ${name}`}</h4>
        <p class="skill-vs-what">${baseline.description}</p>
        <p class="muted">No forecast could be compared with this baseline yet.</p>
      </li>`;
  }
  const ahead = ours.exact - theirs.exact;
  const phrase = BASELINE_PHRASE[baseline.name] || name;
  return html`
    <li class="skill-vs">
      <div class="skill-vs-head">
        <h4>${BASELINE_HEAD[baseline.name] || `Against ${name}`}</h4>
        <span class="skill-vs-n tnum">on ${plural(compared, "forecast")}</span>
      </div>
      <p class="skill-vs-what">${baseline.description}</p>
      <div class="skill-bars" role="group" aria-label=${`Exact band, model against ${name}`}>
        <span class="skill-bars-k">Exact band</span>
        <${Bar} label="This model" rate=${ours.exact_rate} count=${ours.exact}
                of=${ours.scored} kind="model" />
        <${Bar} label=${name} rate=${theirs.exact_rate} count=${theirs.exact}
                of=${theirs.scored} kind="base" />
      </div>
      <div class="skill-bars" role="group"
           aria-label=${`Within one band, model against ${name}`}>
        <span class="skill-bars-k">Within one band</span>
        <${Bar} label="This model" rate=${ours.within_one_rate} count=${ours.within_one}
                of=${ours.scored} kind="model" />
        <${Bar} label=${name} rate=${theirs.within_one_rate} count=${theirs.within_one}
                of=${theirs.scored} kind="base" />
      </div>
      <p class="skill-vs-read">
        ${ahead > 0
          ? `The model called the exact band ${plural(ahead, "more time")} than ${phrase} did.`
          : ahead < 0
            ? `${capital(phrase)} called the exact band ${plural(-ahead, "more time")} than `
              + "the model did."
            : `The model and ${phrase} called the exact `
              + "band equally often."}
      </p>
    </li>`;
}

/* Rows are what the stations measured, columns what the model called; the
   diagonal is a hit. Plain counts, no colour scale — at this sample size a
   heat map would suggest a pattern the numbers cannot carry. */
function Confusion({ confusion }) {
  const [open, setOpen] = useState(false);
  if (!confusion) return null;
  return html`
    <details class="skill-confusion" open=${open} onToggle=${(e) => setOpen(e.target.open)}>
      <summary>What was called against what happened</summary>
      <div class="skill-matrix-wrap">
        <table class="skill-matrix">
          <caption>Rows: the band stations measured. Columns: the band the model called.</caption>
          <thead>
            <tr>
              <th scope="col"><span class="visually-hidden">Measured</span></th>
              ${BANDS.map((b) => html`<th scope="col" key=${b}>
                <${RiskChip} risk=${b} /></th>`)}
            </tr>
          </thead>
          <tbody>
            ${BANDS.map((obs) => html`
              <tr key=${obs}>
                <th scope="row"><${RiskChip} risk=${obs} /></th>
                ${BANDS.map((called) => {
                  const n = (confusion[obs] || {})[called] || 0;
                  return html`<td key=${called}
                    class=${`tnum${obs === called ? " is-hit" : ""}${n ? "" : " is-zero"}`}>
                    ${n}</td>`;
                })}
              </tr>`)}
          </tbody>
        </table>
      </div>
    </details>`;
}

function Verdict({ record }) {
  const o = record.outcome;
  if (!o) {
    return html`
      <span class="ledger-verdict is-pending">
        <${PendingIcon} /> Pending — window closes ${inDays(Date.parse(record.window_end))}
      </span>`;
  }
  if (o.status === "unscorable") {
    return html`<span class="ledger-verdict is-unscorable">Could not be scored</span>`;
  }
  const off = Math.abs(o.band_error || 0);
  const tone = off === 0 ? "is-exact" : off === 1 ? "is-near" : "is-miss";
  const text = off === 0 ? "Exact" : off === 1 ? "Off by one band" : `Off by ${off} bands`;
  return html`<span class=${`ledger-verdict ${tone}`}>${text}</span>`;
}

function LedgerRow({ record }) {
  const o = record.outcome;
  return html`
    <li class=${`ledger-row${o ? "" : " is-pending"}`}>
      <div class="ledger-where">
        <strong>${record.location_name
          || `${record.latitude.toFixed(2)}, ${record.longitude.toFixed(2)}`}</strong>
        <span class="muted tnum">Made ${shortWhen(record.made_at)} · ${record.horizon_hours} h
          ahead</span>
      </div>
      <div class="ledger-bands">
        <span class="ledger-k">Called</span>
        <${RiskChip} risk=${record.risk} />
        <span class="ledger-k">Measured</span>
        ${o && o.observed_band
          ? html`<${RiskChip} risk=${o.observed_band} />`
          : html`<span class="ledger-none">${o ? "—" : "not yet"}</span>`}
      </div>
      <${Verdict} record=${record} />
      ${o && o.status === "unscorable" && o.reason && html`
        <p class="ledger-reason">${o.reason}</p>`}
    </li>`;
}

function Ledger({ ledger }) {
  if (ledger === null) return html`<div class="skeleton skill-skeleton"></div>`;
  if (ledger === false) {
    return html`<p class="note is-bad">The ledger could not be read.</p>`;
  }
  if (!ledger.length) {
    return html`<p class="note">The ledger is empty: no outlook has been made on this node
      yet. The first corridor someone opens starts it.</p>`;
  }
  return html`
    <ol class="ledger-list">
      ${ledger.map((r) => html`<${LedgerRow} key=${r.forecast_id} record=${r} />`)}
    </ol>`;
}

function Scores({ skill }) {
  const small = skill.scored < SMALL_SAMPLE;
  if (!skill.scored) {
    return html`
      <div class="skill-empty">
        <p><strong>No forecast has been scored yet.</strong>${" "}
          ${skill.recorded
            ? `${plural(skill.recorded, "forecast")} recorded in the last ${skill.window_days}
              days; ${skill.pending} still waiting for their window to close${skill.unscorable
                ? `, ${skill.unscorable} with no station close enough to check` : ""}.`
            : `Nothing has been recorded in the last ${skill.window_days} days.`}</p>
        <p class="muted">Rates appear once outlooks have been checked against station
          readings. Until then there is nothing to show — not a rate of zero.</p>
      </div>`;
  }
  return html`
    <div class="skill-top">
      <div class=${`skill-n${small ? " is-small" : ""}`}>
        <strong class="tnum">${skill.scored}</strong>
        <span>${skill.scored === 1 ? "forecast scored" : "forecasts scored"}${" "}
          in the last ${skill.window_days} days</span>
        <ul class="skill-n-sub tnum">
          <li>${skill.pending} pending</li>
          <li>${skill.unscorable} could not be scored</li>
          <li>${skill.recorded} recorded</li>
        </ul>
        ${small && html`
          <p class="skill-small">Fewer than ${SMALL_SAMPLE} scored: read every rate below as${" "}
            anecdote, not evidence.</p>`}
      </div>
      <div class="skill-overall">
        <span class="eyebrow">This model, all scored forecasts</span>
        <p><strong class="tnum">${rateText(skill.forecast.exact_rate)}</strong>
          <span>exact band <small class="tnum">${
            `${skill.forecast.exact} of ${skill.forecast.scored}`}</small></span></p>
        <p><strong class="tnum">${rateText(skill.forecast.within_one_rate)}</strong>
          <span>within one band <small class="tnum">${
            `${skill.forecast.within_one} of ${skill.forecast.scored}`}</small></span></p>
      </div>
    </div>
    <ul class="skill-vs-list">
      ${(skill.baselines || []).map((b) => html`<${Versus} key=${b.name} baseline=${b} />`)}
    </ul>
    <${Confusion} confusion=${skill.forecast.confusion} />`;
}

export function ForecastSkill() {
  const { skill, ledger, errors } = useForecastSkill();
  return html`
    <section class="skill" aria-labelledby="skill-title">
      <header class="skill-head">
        <span class="skill-mark" aria-hidden="true"><${TargetIcon} /></span>
        <div>
          <h2 id="skill-title">How good the forecasts have been</h2>
          <p>Every outlook is written to a ledger before its window opens, then checked
            against what reference stations measured once it closes. It is scored beside two
            simple guesses it has to beat: carrying the last day forward, and the raw CAMS
            forecast with no model.</p>
          <p class="forecast-label">
            <${ModelMark}>Model-derived<//>
            <span>A record of a model's reasoning, not an official forecast's accuracy.</span>
          </p>
        </div>
      </header>

      ${skill === null && html`<div class="skeleton skill-skeleton"></div>`}
      ${skill === false && html`
        <p class="note is-bad">The scores could not be read${errors.skill
          ? `: ${errors.skill}` : ""}.</p>`}
      ${skill && html`<${Scores} skill=${skill} />`}

      ${skill && html`
        <aside class="skill-caveat">
          <strong>Read with care</strong>
          <p>${skill.caveat}</p>
          ${skill.band_basis && html`<p class="skill-basis">${skill.band_basis}</p>`}
        </aside>`}

      <div class="timeline-head skill-ledger-head">
        <h3 class="section-label">Latest entries in the ledger</h3>
        ${skill && html`<p class="timeline-progress tnum">forecaster v${
          skill.forecaster_version}</p>`}
      </div>
      <${Ledger} ledger=${ledger} />
    </section>`;
}

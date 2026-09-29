/* The stage timeline. Each stage shows what it actually decided rather than a
 * spinner: a citizen watching a five-minute run should be able to see the case
 * being built, and disagree with it early.
 *
 * The four stages are one continuous rail rather than four boxes, because the
 * thing being communicated is a sequence with a position in it. Each node
 * carries its state three ways — a shape, a word, and a colour — so it is
 * still legible in glare, in greyscale, and with animation switched off. */

import { useState } from "../vendor/hooks.mjs";
import { html, Fragment } from "../lib/html.js";
import { STAGES, STAGE_INDEX, words, isStatutory } from "../lib/format.js";
import {
  CheckIcon, CrossIcon, ModelIcon, SatelliteIcon, StationIcon, EscalateIcon,
} from "./Icons.js";

const STATE_WORD = {
  done: "Done",
  active: "Working",
  pending: "Waiting",
  failed: "Stopped",
};

/* Past this many characters a model's note is clamped to three lines behind a
 * "Show more". The notes are useful and long — the corroboration one has run
 * to twenty-five lines — and they were burying the stages either side. */
const CLAMP_ABOVE = 220;

function Clamped({ text }) {
  const [open, setOpen] = useState(false);
  const long = text.length > CLAMP_ABOVE;
  return html`
    <div class="case-notes">
      <p class="case-notes-head"><${ModelIcon} />Model notes</p>
      <p class=${`case-notes-text${long && !open ? " is-clamped" : ""}`}>${text}</p>
      ${long && html`
        <button type="button" class="case-more" aria-expanded=${open}
                onClick=${() => setOpen(!open)}>${open ? "Show less" : "Show more"}</button>`}
    </div>`;
}

/* Sixteen points is as fine as a wind bearing is worth reading. */
const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
const compass = (deg) => COMPASS[Math.round((((deg % 360) + 360) % 360) / 22.5) % 16];

/* One measurement: an icon, a figure, a short caption. The full sentence the
   stage wrote sits in the tooltip and, clamped, under the figure. */
function Stat({ label, icon, value, unit, caption, title }) {
  return html`
    <div class="case-stat" title=${title || null}>
      <span class="case-stat-label"><span class="case-stat-icon">${icon}</span>${label}</span>
      <span class="case-stat-body">
        <span class="case-stat-value tnum">${value}${unit
          ? html`<small>${unit}</small>` : ""}</span>
        <span class="case-stat-caption">${caption}</span>
      </span>
    </div>`;
}

const WindArrow = ({ from }) => html`
  <svg viewBox="0 0 24 24" aria-hidden="true"
       style=${`transform: rotate(${(from + 180) % 360}deg)`}>
    <path d="M12 20V5M6.5 10.5 12 5l5.5 5.5" />
  </svg>`;

/* A 0–1 confidence as a bar and a number. Always drawn where evidence is:
   a classification without its confidence is a claim without its caveat. */
function Confidence({ value, halted }) {
  const pct = Math.round((value || 0) * 100);
  return html`
    <div class=${`case-conf${halted ? " is-low" : ""}`}>
      <span class="case-conf-label">Confidence</span>
      <span class="case-conf-bar" aria-hidden="true"><i style=${`width:${pct}%`}></i></span>
      <strong class="tnum">${pct}%</strong>
      ${halted && html`<span class="case-conf-note">below the floor · held for review</span>`}
    </div>`;
}

function detailFor(key, c) {
  if (key === "evidence" && c.evidence) {
    const e = c.evidence;
    const seen = e.visible_indicators || [];
    return html`
      <div class="case-detail">
        <div class="case-chips">
          <span class="case-chip is-kind">${words(e.pollution_type)}</span>
          <span class="case-chip case-sev" data-sev=${e.severity}>${e.severity}</span>
        </div>
        <${Confidence} value=${e.confidence} halted=${c.status === "rejected"} />
        ${seen.length > 0 && html`
          <ul class="case-seen" aria-label="Visible in the photograph">
            ${seen.map((item, i) => html`<li key=${i}>${item}</li>`)}
          </ul>`}
      </div>`;
  }
  if (key === "corroboration" && c.corroboration) {
    const k = c.corroboration;
    const fires = k.satellite_fire_detections || 0;
    return html`
      <div class="case-detail">
        <div class="case-chips">
          ${k.corroborated
            ? html`<span class="case-chip is-yes"><${CheckIcon} />Corroborated</span>`
            : html`<span class="case-chip is-no"
                title="No sensor returned a positive reading. That does not mean the report is wrong: hyper-local events often escape distant stations and satellites."
              >Not corroborated</span>`}
        </div>
        <div class="case-stats">
          <${Stat} label="Satellite" icon=${html`<${SatelliteIcon} />`} value=${fires}
            caption=${fires === 1 ? "fire detection nearby" : "fire detections nearby"}
            title=${k.satellite_summary} />
          <${Stat} label="Station" icon=${html`<${StationIcon} />`}
            value=${k.nearest_station_km == null ? "—" : k.nearest_station_km.toFixed(1)}
            unit=${k.nearest_station_km == null ? "" : " km away"}
            caption=${k.air_quality_summary || "no station reading"}
            title=${k.air_quality_summary} />
          <${Stat} label="Wind" icon=${k.wind_from_degrees == null ? "" : html`
              <${WindArrow} from=${k.wind_from_degrees} />`}
            value=${k.wind_speed_ms == null ? "—" : k.wind_speed_ms}
            unit=${k.wind_speed_ms == null ? "" : " m/s"}
            caption=${k.wind_from_degrees == null ? "no wind reading"
              : `wind from ${compass(k.wind_from_degrees)} (${Math.round(k.wind_from_degrees)}°)`} />
        </div>
        ${k.upwind_source_latitude != null && html`
          <p class="case-meta tnum">
            Upwind back-trace · ${k.upwind_source_latitude}, ${k.upwind_source_longitude}
          </p>`}
        ${k.corroboration_notes && html`<${Clamped} text=${k.corroboration_notes} />`}
      </div>`;
  }
  if (key === "jurisdiction" && c.jurisdiction) {
    const j = c.jurisdiction;
    /* A follow-up interval is not a legal deadline, and the chip says so in its
       own words rather than in a footnote a reader might skip. */
    const statutory = isStatutory(j);
    return html`
      <div class="case-detail">
        <p class="case-authority">
          <strong>${j.authority_name}</strong>
          <span class="case-chip">${j.authority_tier}</span>
        </p>
        <p class="case-meta">${j.statute}${j.section ? ` — ${j.section}` : ""}</p>
        <div class="case-chips">
          ${statutory
            ? html`<span class="case-chip is-yes tnum">
                ${j.response_window_days}-day response window · statutory</span>`
            : html`<span class="case-chip is-info tnum"
                title="No law sets a deadline here; this is the system's suggested follow-up.">
                ${j.response_window_days}-day follow-up · not statutory</span>`}
          ${j.escalation_authority && html`
            <span class="case-chip"><${EscalateIcon} />${j.escalation_authority}</span>`}
        </div>
      </div>`;
  }
  if (key === "drafting" && c.complaint) {
    return html`<p class="case-subject">${c.complaint.subject}</p>`;
  }
  return null;
}

function stateOf(index, c) {
  const reached = STAGE_INDEX[c.stage] ?? 0;
  /* Halted before the evidence stage ran — refused on where the report is,
     before any model was called — means no stage finished at all. */
  if (c.stage === "halted" && !c.evidence) return "pending";
  if (c.stage === "halted") return index === 0 ? "done" : "pending";
  if (index < reached) return "done";
  if (index > reached) return "pending";
  if (c.status === "failed") return "failed";
  if (c.stage === "complete") return "done";
  return "active";
}

/* A node is a filled tick, a breathing ring, an empty circle or a cross. The
 * ring and the circle are drawn in CSS; only the two glyphs need markup. */
function Node({ state }) {
  if (state === "done") return html`<span class="step-node"><${CheckIcon} /></span>`;
  if (state === "failed") return html`<span class="step-node"><${CrossIcon} /></span>`;
  return html`<span class="step-node"></span>`;
}

export function Timeline({ record }) {
  const states = STAGES.map((_, i) => stateOf(i, record));
  const done = states.filter((s) => s === "done").length;
  const running = states.includes("active");

  return html`
    <${Fragment}>
      <div class="timeline-head">
        <h3 class="section-label">How this case was built</h3>
        <p class="timeline-progress case-progress">
          <span class="case-progress-bar" aria-hidden="true">
            ${states.map((st, i) => html`<i key=${i} data-state=${st}></i>`)}
          </span>
          ${running ? `Stage ${done + 1} of ${STAGES.length}` : `${done} of ${STAGES.length} done`}
        </p>
      </div>
      <ol class="timeline">
        ${STAGES.map((stage, i) => {
          const state = states[i];
          /* Before a stage has produced anything, its own blurb says what it
             is about to do — which is more use than the word "working". */
          const detail = detailFor(stage.key, record) ?? stage.blurb;
          return html`
            <li class="step" key=${stage.key} data-state=${state}
                aria-current=${state === "active" ? "step" : null}>
              <${Node} state=${state} />
              <div class="step-body">
                <div class="step-head">
                  <h4>${stage.title}</h4>
                  <span class="step-state">${STATE_WORD[state]}</span>
                </div>
                <div class="detail">${detail}</div>
              </div>
            </li>`;
        })}
        ${record.status === "rejected" && record.error && html`
          <li class="step" data-state="failed">
            <${Node} state="failed" />
            <div class="step-body">
              <div class="step-head">
                <h4>Not taken up</h4>
                <span class="step-state">Stopped before any model call</span>
              </div>
              <div class="detail">${record.error}</div>
            </div>
          </li>`}
        ${record.status === "failed" && record.error && html`
          <li class="step" data-state="failed">
            <${Node} state="failed" />
            <div class="step-body">
              <div class="step-head">
                <h4>Run failed</h4>
                <span class="step-state">Stopped</span>
              </div>
              <div class="detail">${record.error}</div>
            </div>
          </li>`}
      </ol>
    <//>`;
}

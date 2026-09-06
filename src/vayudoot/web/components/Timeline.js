/* The stage timeline. Each stage shows what it actually decided rather than a
 * spinner: a citizen watching a five-minute run should be able to see the case
 * being built, and disagree with it early.
 *
 * The four stages are one continuous rail rather than four boxes, because the
 * thing being communicated is a sequence with a position in it. Each node
 * carries its state three ways — a shape, a word, and a colour — so it is
 * still legible in glare, in greyscale, and with animation switched off. */

import { html, Fragment } from "../lib/html.js";
import { STAGES, STAGE_INDEX, words } from "../lib/format.js";
import { CheckIcon, CrossIcon } from "./Icons.js";

const STATE_WORD = {
  done: "Done",
  active: "Working",
  pending: "Waiting",
  failed: "Stopped",
};

function Detail({ pairs }) {
  return html`
    <dl>
      ${Object.entries(pairs).map(([term, value]) => html`
        <${Fragment} key=${term}><dt>${term}</dt><dd>${String(value)}</dd><//>`)}
    </dl>`;
}

function detailFor(key, c) {
  if (key === "evidence" && c.evidence) {
    const halted = c.status === "rejected";
    return html`<${Detail} pairs=${{
      "Classified": `${words(c.evidence.pollution_type)} — ${c.evidence.severity}`,
      "Confidence": `${(c.evidence.confidence * 100).toFixed(0)}%`
        + (halted ? " — below the floor, halted for human review" : ""),
      "Visible": c.evidence.visible_indicators.join(", ") || "none recorded",
    }} />`;
  }
  if (key === "corroboration" && c.corroboration) {
    const k = c.corroboration;
    return html`<${Detail} pairs=${{
      "Independent evidence": k.corroborated ? "corroborated" : "not corroborated",
      "Satellite": `${k.satellite_fire_detections} detection(s). ${k.satellite_summary || ""}`,
      "Air quality": k.air_quality_summary || "no reading",
      "Wind": k.wind_speed_ms == null
        ? "no reading" : `${k.wind_speed_ms} m/s from ${k.wind_from_degrees}°`,
      "Upwind source": k.upwind_source_latitude == null
        ? "not back-traced" : `${k.upwind_source_latitude}, ${k.upwind_source_longitude}`,
      "Notes": k.corroboration_notes || "—",
    }} />`;
  }
  if (key === "jurisdiction" && c.jurisdiction) {
    const j = c.jurisdiction;
    return html`<${Detail} pairs=${{
      "Authority": `${j.authority_name} (${j.authority_tier})`,
      "Statute": `${j.statute}${j.section ? ` — ${j.section}` : ""}`,
      "Response window": `${j.response_window_days} days`,
      "Escalates to": j.escalation_authority || "—",
    }} />`;
  }
  if (key === "drafting" && c.complaint) return c.complaint.subject;
  return null;
}

function stateOf(index, c) {
  const reached = STAGE_INDEX[c.stage] ?? 0;
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
        <p class="timeline-progress">
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

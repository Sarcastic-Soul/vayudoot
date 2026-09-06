/* The stage timeline. Each stage shows what it actually decided rather than a
 * spinner: a citizen watching a five-minute run should be able to see the case
 * being built, and disagree with it early. */

import { html, Fragment } from "../lib/html.js";
import { STAGES, STAGE_INDEX, words } from "../lib/format.js";

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

export function Timeline({ record }) {
  return html`
    <ol class="timeline">
      ${STAGES.map((stage, i) => {
        const state = stateOf(i, record);
        const detail = detailFor(stage.key, record)
          ?? (state === "active" ? "Working…" : stage.blurb);
        return html`
          <li class="step" key=${stage.key} data-state=${state}>
            <h4>${stage.title}</h4>
            <div class="detail">${detail}</div>
          </li>`;
      })}
      ${record.status === "failed" && record.error && html`
        <li class="step" data-state="failed">
          <h4>Run failed</h4>
          <div class="detail">${record.error}</div>
        </li>`}
    </ol>`;
}

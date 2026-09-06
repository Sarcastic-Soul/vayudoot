/* Small shared shapes. Everything here is pure, so components stay about
 * layout rather than about string handling. */

export const STAGES = [
  { key: "evidence", title: "Evidence", blurb: "Reading the photograph" },
  { key: "corroboration", title: "Corroboration", blurb: "Satellite, ground stations, wind" },
  { key: "jurisdiction", title: "Jurisdiction", blurb: "Who is responsible for this location" },
  { key: "drafting", title: "Drafting", blurb: "Writing the formal complaint" },
];

export const STAGE_INDEX = {
  received: 0, evidence: 0, corroboration: 1, jurisdiction: 2, drafting: 3,
  complete: 4, halted: 4,
};

/* A run is over when the pipeline reached the end, halted at the confidence
 * floor, or failed. A failed case keeps the stage it died on. */
export const isFinished = (c) =>
  c.stage === "complete" || c.stage === "halted" || c.status === "failed";

/* Escalation is only offered once the statutory window has actually lapsed;
 * the server refuses it before that, so the button should not be there. */
export function escalationDue(c) {
  if (c.status !== "filed" || !c.filed_at || !c.jurisdiction) return false;
  const days = c.jurisdiction.response_window_days;
  return Date.now() >= Date.parse(c.filed_at) + days * 86400000;
}

export const words = (value) => String(value).replace(/_/g, " ");

export const whereOf = (c) => c.address || `${c.report.latitude}, ${c.report.longitude}`;

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

/* When a case was opened, in the shortest form that is still unambiguous.
 * Recent cases are the ones a citizen is looking for, so those get a relative
 * phrase; anything older gets a date, because "43 days ago" is not a date
 * anybody can act on. Falls back to an empty string rather than to "Invalid
 * Date" if the server ever sends something unparseable. */
export function shortWhen(iso) {
  const at = Date.parse(iso);
  if (!iso || Number.isNaN(at)) return "";
  const mins = Math.round((Date.now() - at) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} ${hours === 1 ? "hour" : "hours"} ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days} ${days === 1 ? "day" : "days"} ago`;
  return new Date(at).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export const whereOf = (c) => c.address || `${c.report.latitude}, ${c.report.longitude}`;

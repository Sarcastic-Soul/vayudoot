/* Small shared shapes. Everything here is pure, so components stay about
 * layout rather than about string handling.
 *
 * The lifecycle predicates below are the client's copy of rules the server
 * enforces — `TERMINAL_STATUSES` in `schemas.py`, the `*_FROM` tuples in
 * `lifecycle.py`, and `ESCALATION_CLOCK` in `filing.py`. They are duplicated
 * deliberately: the interface must not offer a control the API would answer
 * with a 409, and the only way to know that before pressing it is to know the
 * same rule. They live together here so the copy is one file to check against
 * the server rather than a condition scattered through four components. */

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

/* Statuses nothing moves out of — `TERMINAL_STATUSES` in schemas.py. A case in
 * one of these is finished, well or badly, so it cannot be filed, escalated or
 * withdrawn and there is nothing left to poll for. */
export const TERMINAL = ["resolved", "withdrawn", "rejected", "failed"];

export const isTerminal = (c) => TERMINAL.includes(c.status);

/* A run is over when the pipeline reached the end, halted at the confidence
 * floor, or the case has ended. A failed case keeps the stage it died on. */
export const isFinished = (c) =>
  c.stage === "complete" || c.stage === "halted" || isTerminal(c);

/* Which date the escalation clock runs from, per status — `ESCALATION_CLOCK`
 * in filing.py. An acknowledgement restarts the clock rather than stopping it,
 * so an acknowledged case is escalatable again a full window after the reply.
 * `escalated` is absent because a case is escalated once. */
const ESCALATION_CLOCK = { filed: "filed_at", acknowledged: "acknowledged_at" };

/* When this case becomes escalatable, in epoch milliseconds, or null when no
 * clock is running at all. */
export function escalatableAt(c) {
  const field = ESCALATION_CLOCK[c.status];
  if (!field || !c.jurisdiction) return null;
  const started = Date.parse(c[field]);
  if (Number.isNaN(started)) return null;
  return started + c.jurisdiction.response_window_days * 86400000;
}

/* Escalation is only offered once the statutory window has actually lapsed;
 * the server refuses it before that, so the button should not be there. */
export function escalationDue(c) {
  const due = escalatableAt(c);
  return due !== null && Date.now() >= due;
}

/* The three lifecycle transitions, each mirroring its `*_FROM` tuple. An
 * authority can only respond to something it was sent; a case can be closed
 * whether or not anyone acknowledged it; anything not already over can be
 * taken back. */
export const canAcknowledge = (c) => c.status === "filed" || c.status === "escalated";

export const canResolve = (c) =>
  c.status === "filed" || c.status === "escalated" || c.status === "acknowledged";

export const canWithdraw = (c) => !isTerminal(c);

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

/* A calendar date, written out. Used wherever a date is part of the record
 * rather than part of the chrome — when a response arrived, when a case was
 * closed, when it becomes escalatable — because those are dates a citizen may
 * have to quote back at somebody. */
export function onDate(value) {
  const at = typeof value === "number" ? value : Date.parse(value);
  if (value == null || Number.isNaN(at)) return "";
  return new Date(at).toLocaleDateString(undefined, {
    day: "numeric", month: "long", year: "numeric",
  });
}

/* The date and the time, for the case history, where the order of two entries
 * a minute apart is the thing being read. */
export function atTime(at) {
  return new Date(at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/* How far off a future moment is, phrased to end a sentence. */
export function inDays(at) {
  const days = Math.ceil((at - Date.now()) / 86400000);
  if (days <= 0) return "today";
  if (days === 1) return "tomorrow";
  return `in ${days} days`;
}

/* Today, as the `value` and `max` of a date input. Built from the local date
 * rather than from `toISOString`, which would hand a reader east of UTC
 * yesterday's date for most of their evening. */
export function todayISO() {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

/* A byte limit, said the way an upload dialog says it. */
export function megabytes(bytes) {
  const mb = bytes / (1024 * 1024);
  return `${mb >= 10 || Number.isInteger(mb) ? Math.round(mb) : mb.toFixed(1)} MB`;
}

export const whereOf = (c) => c.address || `${c.report.latitude}, ${c.report.longitude}`;

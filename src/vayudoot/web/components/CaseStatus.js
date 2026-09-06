/* What state this case is in, said properly.
 *
 * Awaiting confirmation, filed, escalated, rejected and failed are five
 * different situations, not five shades of one. A pill could only ever say
 * which word applied; this says what it means and what happens next, which is
 * the part a citizen actually needs. The tone drives the colour, the icon and
 * the border, so a status can never be half-dressed. */

import { html } from "../lib/html.js";
import { words } from "../lib/format.js";
import { HandIcon, FiledIcon, EscalateIcon, HeldIcon, FailedIcon } from "./Icons.js";

/* The window a filed complaint has, phrased as a sentence rather than as a
 * field. Falls back quietly when the jurisdiction stage never ran. */
function windowNote(record) {
  const days = record.jurisdiction && record.jurisdiction.response_window_days;
  if (!days) return "The complaint is in the sandbox outbox.";
  return `The authority has ${days} days to respond. `
    + "You can escalate from here once that window has lapsed.";
}

export function describeStatus(record) {
  if (!record) {
    return { tone: "neutral", Icon: HeldIcon, label: "Loading", headline: "Opening the case…",
      note: "" };
  }

  const authority = record.jurisdiction && record.jurisdiction.authority_name;

  if (record.status === "failed") {
    return {
      tone: "danger",
      Icon: FailedIcon,
      label: "failed",
      headline: "The run did not finish.",
      note: record.error || "The pipeline stopped before it could draft a complaint.",
    };
  }

  if (record.status === "rejected") {
    return {
      tone: "neutral",
      Icon: HeldIcon,
      label: "held for review",
      headline: "Held below the confidence floor.",
      note: "The photograph was not classified confidently enough to draft a complaint "
        + "from. Nothing has been sent, and nothing will be.",
    };
  }

  if (record.status === "escalated") {
    const to = record.jurisdiction && record.jurisdiction.escalation_authority;
    return {
      tone: "info",
      Icon: EscalateIcon,
      label: "escalated",
      headline: to ? `Escalated to ${to}.` : "Escalated.",
      note: "The response window lapsed without an acknowledgement, so the case was "
        + "raised a tier.",
    };
  }

  if (record.status === "filed") {
    return {
      tone: "ok",
      Icon: FiledIcon,
      label: "filed",
      headline: authority ? `Filed to ${authority}.` : "Filed.",
      note: windowNote(record),
    };
  }

  if (record.status === "awaiting_confirmation") {
    return {
      tone: "attention",
      Icon: HandIcon,
      label: "awaiting confirmation",
      headline: "Waiting for you.",
      note: "Nothing has been sent. Read the draft, and file it when you are satisfied "
        + "it is right.",
    };
  }

  /* Still running. The timeline carries the detail; this says only that the
     case is live, so the two do not repeat each other. */
  return {
    tone: "neutral",
    Icon: HeldIcon,
    label: words(record.status),
    headline: "Working on this case.",
    note: "Each stage appears below as it finishes. You can leave and come back.",
  };
}

export function StatusBanner({ record }) {
  const { tone, Icon, headline, note } = describeStatus(record);
  return html`
    <div class="status-banner" data-tone=${tone} aria-live="polite">
      <${Icon} />
      <p class="status-headline">${headline}</p>
      ${note && html`<p class="status-note">${note}</p>`}
    </div>`;
}

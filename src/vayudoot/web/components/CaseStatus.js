/* What state this case is in, said properly.
 *
 * Nine situations that are not shades of one another: still running, waiting
 * for a person, filed, acknowledged, escalated, resolved, withdrawn, held
 * below the confidence floor, and failed. A pill could only ever say which
 * word applied; this says what it means and what happens next, which is the
 * part a citizen actually needs. The tone drives the colour, the icon and the
 * border, so a status can never be half-dressed.
 *
 * Two of the nine carry more than a sentence:
 *
 * - `acknowledged` is the interesting one, because it is neither open nor
 *   finished. An acknowledgement is a receipt, not a remedy, so the escalation
 *   clock restarts from the reply rather than stopping — which means the
 *   banner has to say when the reply came, what it said, and the date the case
 *   becomes escalatable again. Anything less reads as "done".
 * - the four terminal statuses are flagged closed and state why they ended,
 *   because a case nobody will act on again should not look like one that is
 *   merely quiet. */

import { html } from "../lib/html.js";
import { words, onDate, inDays, escalatableAt, isTerminal } from "../lib/format.js";
import {
  HandIcon, FiledIcon, EscalateIcon, HeldIcon, FailedIcon,
  ReplyIcon, ResolvedIcon, WithdrawIcon,
} from "./Icons.js";

/* When the case next becomes escalatable, as a sentence. Empty when no clock
 * is running — an already escalated case, or one that was never filed. */
function clockNote(record) {
  const due = escalatableAt(record);
  if (due === null) return "";
  if (Date.now() >= due) return "That window has lapsed, so you can escalate from here now.";
  return `You can escalate from ${onDate(due)}, ${inDays(due)}.`;
}

/* The window a filed complaint has, phrased as a sentence rather than as a
 * field. Falls back quietly when the jurisdiction stage never ran. */
function windowNote(record) {
  const days = record.jurisdiction && record.jurisdiction.response_window_days;
  if (!days) return "The complaint is in the sandbox outbox.";
  return `The authority has ${days} days to respond. ${clockNote(record)}`.trim();
}

/* A note the citizen or the authority left on a transition, shown as what it
 * is — a quotation — rather than folded into the interface's own prose. */
const said = (label, text) => (text ? { label, text } : null);

export function describeStatus(record) {
  if (!record) {
    return { tone: "neutral", Icon: HeldIcon, label: "Loading", headline: "Opening the case…",
      note: "" };
  }

  const authority = record.jurisdiction && record.jurisdiction.authority_name;
  const closed = isTerminal(record);

  if (record.status === "failed") {
    return {
      tone: "danger",
      Icon: FailedIcon,
      label: "failed",
      closed,
      headline: "The run did not finish.",
      note: record.error || "The pipeline stopped before it could draft a complaint.",
    };
  }

  if (record.status === "rejected") {
    return {
      tone: "neutral",
      Icon: HeldIcon,
      label: "held for review",
      closed,
      headline: "Held below the confidence floor.",
      note: "The photograph was not classified confidently enough to draft a complaint "
        + "from. Nothing has been sent, and nothing will be.",
    };
  }

  if (record.status === "withdrawn") {
    const on = onDate(record.withdrawn_at);
    return {
      tone: "neutral",
      Icon: WithdrawIcon,
      label: "withdrawn",
      closed,
      headline: "You took this complaint back.",
      note: `Withdrawn${on ? ` on ${on}` : ""}. Nothing further will be filed, the case will `
        + "not be chased, and it cannot be reopened.",
      quote: said("Your reason", record.withdrawal_note),
    };
  }

  if (record.status === "resolved") {
    const on = onDate(record.resolved_at);
    return {
      tone: "ok",
      Icon: ResolvedIcon,
      label: "resolved",
      closed,
      headline: "Resolved. The problem was dealt with.",
      note: `Closed${on ? ` on ${on}` : ""}. This is the ending the case was for; nothing `
        + "further is filed and the escalation clock has stopped.",
      quote: said("What happened", record.resolution_note),
    };
  }

  if (record.status === "escalated") {
    const to = record.jurisdiction && record.jurisdiction.escalation_authority;
    const wasAcknowledged = Boolean(record.acknowledged_at);
    return {
      tone: "info",
      Icon: EscalateIcon,
      label: "escalated",
      headline: to ? `Escalated to ${to}.` : "Escalated.",
      note: wasAcknowledged
        ? `${authority || "The authority"} acknowledged this complaint but nothing followed `
          + "within the window after that reply, so the case was raised a tier."
        : "The response window lapsed without an acknowledgement, so the case was "
          + "raised a tier.",
      quote: said("What the first authority said", record.response_note),
    };
  }

  if (record.status === "acknowledged") {
    const on = onDate(record.acknowledged_at);
    return {
      tone: "attention",
      Icon: ReplyIcon,
      label: "acknowledged",
      headline: `${authority || "The authority"} responded${on ? ` on ${on}` : ""}.`,
      note: "An acknowledgement is a receipt, not a remedy, so the clock restarts rather "
        + `than stopping. ${clockNote(record)}`.trim(),
      quote: said("What they said", record.response_note),
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
  const { tone, Icon, headline, note, quote, closed } = describeStatus(record);
  return html`
    <div class="status-banner" data-tone=${tone} data-closed=${closed ? "true" : null}
         aria-live="polite">
      <${Icon} />
      <div class="status-body">
        <p class="status-headline">${headline}</p>
        ${note && html`<p class="status-note">${note}</p>`}
        ${quote && html`
          <blockquote class="status-quote">
            <p class="eyebrow">${quote.label}</p>
            <p>${quote.text}</p>
          </blockquote>`}
      </div>
      ${closed && html`<span class="status-flag">Closed</span>`}
    </div>`;
}

/* The drafted complaint, in English and — where the drafting agent produced one
 * — in the language the authority actually reads. The toggle only appears when
 * there is a second version to toggle to. */

import { useState } from "../vendor/hooks.mjs";
import { html } from "../lib/html.js";

export function Complaint({ complaint }) {
  const [lang, setLang] = useState("en");
  const hasLocal = Boolean(complaint.body_local);
  const showing = hasLocal && lang === "local" ? "local" : "en";

  return html`
    <div class="complaint">
      <div class="complaint-head">
        <p class="eyebrow">The complaint drafted for you</p>
        <h3>${complaint.subject}</h3>
        ${hasLocal && html`
          <div class="lang-toggle">
            <button type="button" class=${showing === "en" ? "is-active" : ""}
                    onClick=${() => setLang("en")}>English</button>
            <button type="button" class=${showing === "local" ? "is-active" : ""}
                    onClick=${() => setLang("local")}>
              ${complaint.local_language || "Local language"}
            </button>
          </div>`}
      </div>
      <pre>${showing === "local" ? complaint.body_local : complaint.body_en}</pre>
      ${complaint.cited_statutes.length > 0 && html`
        <p class="statutes">
          <span class="statutes-label">Cited under</span>
          ${complaint.cited_statutes.join("; ")}
        </p>`}
    </div>`;
}

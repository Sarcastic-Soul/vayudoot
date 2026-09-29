/* What the reporter said, as a model heard it.
 *
 * The transcript comes first and in the language it was spoken, set with its
 * own `lang` so the browser picks the right font and a screen reader the right
 * voice. The English translation sits under it, because the authority reading
 * the case may not share the reporter's language, and the reporter should be
 * able to check the translation against what they said.
 *
 * Three things are always on screen, never behind a click:
 *
 * - "Heard by a model", in the model-derived mark every predictive panel
 *   wears. A transcript looks like a record; it is a model's hearing, and can
 *   be wrong the way hearing is wrong.
 * - The server's disclaimer, verbatim: this is the reporter's own claim, the
 *   same person as the rest of the report, so it corroborates nothing.
 * - That names were left out, when any were. Every name is replaced before
 *   the account is stored (`agents/voice.py`), and the placeholder is drawn as
 *   a gap rather than as text, so nobody reads it as a name.
 *
 * The recording itself is not offered. No route serves it: a voice identifies
 * the speaker, and a case is world-readable.
 */

import { html, Fragment } from "../lib/html.js";
import { words } from "../lib/format.js";
import { ModelIcon } from "./Icons.js";

const OMITTED = "[name omitted]";

/* The placeholder, drawn as a redaction rather than as words in brackets. */
function withGaps(text) {
  const parts = String(text || "").split(OMITTED);
  return parts.map((part, i) => html`<${Fragment} key=${i}>${part}${
    i < parts.length - 1 && html`<span class="voice-gap" title="A name was left out here">name
      left out</span>`}<//>`);
}

/* One extracted detail. Short phrases are chips; a sentence is just text. */
function Fact({ label, value, prose = false }) {
  if (!value || (Array.isArray(value) && !value.length)) return null;
  const items = Array.isArray(value) ? value : [value];
  return html`
    <div class="voice-fact">
      <dt>${label}</dt>
      <dd>${prose
        ? html`<span class="voice-prose">${withGaps(value)}</span>`
        : items.map((item, i) => html`
            <span key=${i} class="voice-chip">${withGaps(item)}</span>`)}</dd>
    </div>`;
}

export function VoiceAccount({ voice }) {
  if (!voice) return null;
  const language = voice.language || "an unidentified language";
  const english = /^en\b/i.test(voice.language_code || "") || /^english$/i.test(voice.language);

  return html`
    <section class="voice-account" aria-labelledby="voice-account-title">
      <div class="voice-account-head">
        <h3 class="section-label" id="voice-account-title">What the reporter said</h3>
        <span class="model-mark"><${ModelIcon} />Heard by a model</span>
      </div>

      ${!voice.heard_speech
        ? html`
          <p class="voice-empty">The voice note had no speech that could be made out.</p>`
        : html`
          <figure class="voice-quote">
            <figcaption>
              <span class="voice-lang-chip">${language}${voice.language_code
                ? html`<span class="muted"> · ${voice.language_code}</span>` : ""}</span>
              <span class="muted">As spoken</span>
            </figcaption>
            <blockquote lang=${voice.language_code || undefined}>${withGaps(voice.transcript)}</blockquote>
          </figure>

          ${!english && voice.translation_en && html`
            <figure class="voice-quote is-translation">
              <figcaption>
                <span class="voice-lang-chip">English</span>
                <span class="muted">Translated by the same model</span>
              </figcaption>
              <blockquote lang="en">${withGaps(voice.translation_en)}</blockquote>
            </figure>`}

          <dl class="voice-facts">
            <${Fact} label="Describes" value=${voice.what_is_described} prose />
            <${Fact} label="When" value=${voice.time_pattern} />
            <${Fact} label="For how long" value=${voice.duration} />
            <${Fact} label="Smells" value=${voice.smells} />
            <${Fact} label="Effects on health" value=${voice.health_effects} />
            <${Fact} label="Sounds like"
              value=${voice.pollution_type_hint && voice.pollution_type_hint !== "unclear"
                ? words(voice.pollution_type_hint) : ""} />
          </dl>`}

      ${voice.names_omitted > 0 && html`
        <p class="voice-names">
          <span class="voice-gap" aria-hidden="true">name left out</span>
          <span title="This service never names a person or a business, even when the reporter does.">
            ${voice.names_omitted} ${voice.names_omitted === 1 ? "name" : "names"} left out on
            purpose.</span>
        </p>`}

      <aside class="disclaimer is-compact">
        <${ModelIcon} />
        <div>
          <p>${voice.disclaimer}</p>
          <p class="muted">Recording kept private.</p>
        </div>
      </aside>
    </section>`;
}

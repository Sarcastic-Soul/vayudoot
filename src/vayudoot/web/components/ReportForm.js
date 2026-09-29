/* The only thing a citizen has to fill in: a pin, and a photograph or a voice
 * note. Everything else is optional, because standing in front of a burning
 * waste heap is not the moment for a form.
 *
 * The voice note (`VoiceRecorder`) is in whatever language the citizen speaks.
 * It is sent as one more multipart field, `audio`, and the server refuses it
 * with the same 413 and 415 as a photograph, so the handling below covers it.
 *
 * Two ways this form can now be refused, and neither is the citizen's fault:
 *
 * - 413, the photograph is larger than the instance will take. A modern phone
 *   camera clears the limit easily, so this is common rather than exotic. The
 *   ceiling comes from `/health`, which lets the well say the limit before a
 *   file is chosen and lets an oversized one be caught the moment it is
 *   picked — refusing it here costs nothing, where refusing it after the
 *   upload costs a photograph pushed over a phone connection first.
 * - 429, the instance is out of budget. A report is about ten model calls
 *   against a free tier, so the day's allowance is finite and public: the
 *   remaining count is shown while it is running low, and an exhausted one is
 *   said before the form is filled in rather than after it is submitted.
 *
 * Both are drawn in `attention` rather than `danger`. A limit is not a fault,
 * and the one thing a person needs to hear either way is that nothing was
 * sent and the form still holds what they put in it. */

import { useRef, useState } from "../vendor/hooks.mjs";
import { html } from "../lib/html.js";
import { api } from "../lib/api.js";
import { navigate } from "../lib/router.js";
import { useHealth } from "../lib/store.js";
import { megabytes } from "../lib/format.js";
import { LocationPicker } from "./LocationPicker.js";
import { CameraIcon, ClockIcon, ImagePlusIcon, LockIcon, PinIcon, SendIcon } from "./Icons.js";
import { VoiceRecorder } from "./VoiceRecorder.js";

/* Below this the remaining daily budget is worth saying out loud. Above it,
 * saying so would be noise about a limit nobody is near. */
const LOW_BUDGET = 3;

/* Nothing was lost, and the form still holds it. The server cannot say this;
 * it is the one thing a person wants to know when a submission is refused. */
const KEPT = "Nothing was submitted. Everything you added, and your pin, is still here.";

function whenAgain(seconds) {
  if (!seconds) return "";
  const at = new Date(Date.now() + seconds * 1000);
  const clock = at.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  const sameDay = at.toDateString() === new Date().toDateString();
  return ` You can try again after ${clock}${sameDay ? "" : " tomorrow"}.`;
}

/* An HTTP status turned into something addressed to a person. The server's own
 * sentences are good and are used as they stand; what is added here is the
 * tone, and the part the server has no way of knowing. */
function describeFailure(error) {
  if (error.status === 413) {
    return { tone: "attention", detail: error.message, hint: KEPT };
  }
  if (error.status === 429) {
    return { tone: "attention", detail: error.message, hint: KEPT + whenAgain(error.retryAfter) };
  }
  if (error.status === 415) {
    return { tone: "attention", detail: error.message, hint: KEPT };
  }
  return {
    tone: "danger",
    detail: error.message,
    hint: "Nothing was submitted. If this keeps happening the instance may be down.",
  };
}

export function ReportForm() {
  const [point, setPoint] = useState(null);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [voice, setVoice] = useState(null);
  const [recording, setRecording] = useState(false);
  const [health, refreshHealth] = useHealth();
  const photo = useRef(null);
  const note = useRef(null);
  const contact = useRef(null);

  const maxBytes = health && health.max_upload_bytes;
  const remaining = health && health.rate_limited ? health.reports_remaining_today : null;

  /* Refused before the upload rather than after it. Same phrasing as the
     server's own 413, because the citizen should not be able to tell which of
     the two turned the file away. */
  function tooLarge(file) {
    if (!maxBytes || file.size <= maxBytes) return null;
    return {
      tone: "attention",
      detail: `That photograph is too large. The limit is ${megabytes(maxBytes)}, and that `
        + `one is ${megabytes(file.size)}.`,
      hint: "Share a reduced-size copy instead — the image is scaled down before it is read "
        + "anyway.",
    };
  }

  function onPhoto(event) {
    const file = event.target.files[0];
    if (!file) return;
    if (preview) URL.revokeObjectURL(preview);
    setPreview(URL.createObjectURL(file));
    setError(tooLarge(file));
  }

  async function onSubmit(event) {
    event.preventDefault();
    setError(null);
    if (!point) {
      setError({
        tone: "attention",
        detail: "Place the pin first: it decides which authority receives this.",
      });
      return;
    }

    const file = photo.current.files[0];
    const oversized = file && tooLarge(file);
    if (oversized) {
      setError(oversized);
      return;
    }

    const body = new FormData();
    body.append("latitude", point.latitude);
    body.append("longitude", point.longitude);
    body.append("note", note.current.value);
    body.append("contact", contact.current.value);
    if (file) body.append("image", file);
    if (voice) body.append("audio", voice.blob, voice.name);

    setBusy(true);
    try {
      const created = await api("/reports", { method: "POST", body });
      navigate(created.case_id);
    } catch (e) {
      setError(describeFailure(e));
    } finally {
      setBusy(false);
      refreshHealth();   // a submission, refused or not, moves the day's count
    }
  }

  return html`
    <header class="page-head report-head">
      <h2>Report a pollution event</h2>
      <p>Drop a pin, add a photo or voice note. We draft the rest.</p>
      <ol class="report-steps" aria-label="How a report works">
        <li><span class="report-step-disc"><${PinIcon} /></span>Pin the place</li>
        <li><span class="report-step-disc"><${CameraIcon} /></span>Photo or voice</li>
        <li><span class="report-step-disc is-model">AI</span>Checked and drafted</li>
        <li><span class="report-step-disc is-you"><${SendIcon} /></span>You confirm</li>
      </ol>
    </header>

    ${remaining === 0 && html`
      <div class="note is-limit" role="status">
        <strong>All ${health.reports_per_day} of today's reports are used.</strong> Resets at
        00:00 UTC — a report sent before then will be refused.
      </div>`}

    <form novalidate onSubmit=${onSubmit}>
      <div class="form-col">
        <label class=${`photo-field${preview ? " has-photo" : ""}`}>
          <span class="field-label">The photograph</span>
          <input type="file" id="photo" name="image" accept="image/*" capture="environment"
                 hidden ref=${photo} onChange=${onPhoto} />
          <div class="photo-drop">
            ${preview
              ? html`<img src=${preview} alt="The photograph you chose" />`
              : html`<div class="photo-hint">
                  <${ImagePlusIcon} />
                  <strong>Add the photograph</strong>
                  <span>Tap to use the camera, or choose a file</span>
                </div>`}
          </div>
          <span class="report-chips">
            ${preview
              ? html`<span class="report-chip">Tap to replace</span>`
              : html`<span class="report-chip">1 image</span>`}
            ${maxBytes ? html`<span class="report-chip tnum">≤ ${megabytes(maxBytes)}</span>` : ""}
          </span>
        </label>

        <${LocationPicker} point=${point} onPoint=${setPoint} />
      </div>

      <div class="form-col">
        <${VoiceRecorder} health=${health} clip=${voice} onClip=${setVoice}
                          onRecording=${setRecording} />

        <div class="field">
          <label for="note">What did you see?</label>
          <textarea id="note" rows="3" ref=${note}
            placeholder="Waste being burnt behind the market since about 8pm. Thick smoke."
          ></textarea>
        </div>

        <div class="field">
          <label for="contact">Your contact <span class="muted">(optional)</span></label>
          <input type="text" id="contact" placeholder="Email or phone" autocomplete="off"
                 ref=${contact} />
        </div>

        <button type="submit" class="primary" disabled=${busy || recording}>
          ${busy ? "Starting the case…" : recording ? "Stop the recording first" : "Run the case"}
        </button>
        <p class="report-assure">
          <span><${ClockIcon} />A few minutes · watch it live</span>
          <span><${LockIcon} />Nothing is filed until you confirm</span>
        </p>
        ${remaining !== null && remaining > 0 && remaining <= LOW_BUDGET && html`
          <p class="submit-note tnum" role="status">
            ${remaining === 1 ? "1 report left" : `${remaining} reports left`} today · resets
            00:00 UTC
          </p>`}
        ${error && html`
          <div class="form-error" data-tone=${error.tone} role="alert">
            <p>${error.detail}</p>
            ${error.hint && html`<p class="hint">${error.hint}</p>`}
          </div>`}
      </div>
    </form>`;
}

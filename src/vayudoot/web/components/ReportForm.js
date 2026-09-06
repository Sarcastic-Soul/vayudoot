/* The only thing a citizen has to fill in: a photograph and a pin. Everything
 * else is optional, because standing in front of a burning waste heap is not
 * the moment for a form. */

import { useRef, useState } from "../vendor/hooks.mjs";
import { html } from "../lib/html.js";
import { api } from "../lib/api.js";
import { navigate } from "../lib/router.js";
import { LocationPicker } from "./LocationPicker.js";

export function ReportForm() {
  const [point, setPoint] = useState(null);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const photo = useRef(null);
  const note = useRef(null);
  const contact = useRef(null);

  function onPhoto(event) {
    const file = event.target.files[0];
    if (!file) return;
    if (preview) URL.revokeObjectURL(preview);
    setPreview(URL.createObjectURL(file));
  }

  async function onSubmit(event) {
    event.preventDefault();
    setError("");
    if (!point) {
      setError("Place the pin first: it decides which authority receives this.");
      return;
    }

    const body = new FormData();
    body.append("latitude", point.latitude);
    body.append("longitude", point.longitude);
    body.append("note", note.current.value);
    body.append("contact", contact.current.value);
    if (photo.current.files[0]) body.append("image", photo.current.files[0]);

    setBusy(true);
    try {
      const created = await api("/reports", { method: "POST", body });
      navigate(created.case_id);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return html`
    <form novalidate onSubmit=${onSubmit}>
      <div class="form-col">
        <label class="photo-field">
          <input type="file" id="photo" name="image" accept="image/*" capture="environment"
                 hidden ref=${photo} onChange=${onPhoto} />
          <div class="photo-drop">
            ${preview
              ? html`<img src=${preview} alt="" />`
              : html`<div class="photo-hint">
                  <strong>Add the photograph</strong>
                  <span>Tap to use the camera, or choose a file</span>
                </div>`}
          </div>
        </label>

        <${LocationPicker} point=${point} onPoint=${setPoint} />
      </div>

      <div class="form-col">
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

        <button type="submit" class="primary" disabled=${busy}>
          ${busy ? "Starting the case…" : "Run the case"}
        </button>
        <p class="error" hidden=${!error}>${error}</p>
      </div>
    </form>`;
}

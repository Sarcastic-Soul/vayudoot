/* The satellite switch on a hotspot map.
 *
 * A circle on a street map is the system's claim; the same circle on
 * yesterday's VIIRS pass is that claim held up against the sky it was made
 * about. This control is how an operator does that check without leaving the
 * page: one base swap (street or true colour), two overlays (aerosol and
 * fires), and the day of the pass. The layers themselves, and why each one is
 * the layer it is, are in `lib/gibs.js`.
 *
 * It sits on the map rather than in a toolbar above it because it changes the
 * map and nothing else. It is a real button with a real panel, not Leaflet's
 * own layers control, because that control cannot hold the two sentences that
 * matter most here: aerosol optical depth is haze and not a PM2.5 reading, and
 * a fire pixel is heat and not a named source.
 *
 * The choice is shared by every hotspot map and remembered per viewer, so a
 * layer turned on in the operations view is still on when a hotspot is opened.
 */

import { useEffect, useRef, useState } from "../vendor/hooks.mjs";
import { html } from "../lib/html.js";
import {
  AEROSOL, GIBS_EARLIEST, anySatellite, setImagery, useImagery, utcToday, utcYesterday,
} from "../lib/gibs.js";
import { LayersIcon, CrossIcon } from "./Icons.js";

let serial = 0;

export function SatelliteControl() {
  const imagery = useImagery();
  const [open, setOpen] = useState(false);
  const [id] = useState(() => `sat-${++serial}`);
  const panel = useRef(null);
  const toggle = useRef(null);
  const today = utcToday();
  const active = [imagery.base === "satellite", imagery.aerosol, imagery.fires]
    .filter(Boolean).length;

  /* Escape closes it and hands focus back, the way the full-screen map does. */
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => {
      if (event.key !== "Escape") return;
      event.stopPropagation();
      setOpen(false);
      if (toggle.current) toggle.current.focus();
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [open]);

  /* Leaflet listens for clicks and wheel events on everything inside the map
     wrapper's stacking context; a scroll inside the panel must not zoom the
     map under it. */
  useEffect(() => {
    if (!panel.current || !window.L) return;
    window.L.DomEvent.disableClickPropagation(panel.current);
    window.L.DomEvent.disableScrollPropagation(panel.current);
  }, [open]);

  const base = (value, label) => html`
    <button type="button" aria-pressed=${imagery.base === value}
            class=${imagery.base === value ? "is-on" : ""}
            onClick=${() => setImagery({ base: value })}>${label}</button>`;

  return html`
    <div class=${`sat-control${open ? " is-open" : ""}`}>
      <button type="button" class=${`sat-toggle${anySatellite(imagery) ? " is-live" : ""}`}
              ref=${toggle} aria-expanded=${open} aria-controls=${id}
              onClick=${() => setOpen((was) => !was)}>
        <${LayersIcon} />
        <span class="sat-toggle-label">Satellite</span>
        ${active > 0 && html`<span class="sat-count tnum" aria-label=${`${active} on`}>
          ${active}</span>`}
      </button>

      ${open && html`
        <div class="sat-panel" id=${id} ref=${panel} role="group"
             aria-label="Satellite layers">
          <div class="sat-panel-head">
            <p class="eyebrow">NASA satellite layers</p>
            <button type="button" class="sat-close" aria-label="Close satellite layers"
                    onClick=${() => { setOpen(false); if (toggle.current) toggle.current.focus(); }}>
              <${CrossIcon} />
            </button>
          </div>

          <div class="sat-seg" role="group" aria-label="Base map">
            ${base("street", "Street map")}
            ${base("satellite", "True colour")}
          </div>

          <label class="sat-check">
            <input type="checkbox" checked=${imagery.aerosol}
                   onChange=${(e) => setImagery({ aerosol: e.target.checked })} />
            <span>
              <strong>Aerosol optical depth</strong>
              <small>How much the whole air column dimmed sunlight. Haze, not a PM2.5
                reading.</small>
            </span>
          </label>
          ${imagery.aerosol && html`
            <figure class="sat-legend">
              <img src=${AEROSOL.legend} alt="Aerosol optical depth scale, clear to very hazy"
                   loading="lazy" />
            </figure>`}

          <label class="sat-check">
            <input type="checkbox" checked=${imagery.fires}
                   onChange=${(e) => setImagery({ fires: e.target.checked })} />
            <span>
              <strong>Fires</strong>
              <small>VIIRS thermal anomalies, 375 m pixels. Heat seen from orbit — it does
                not say what is burning.</small>
            </span>
          </label>

          <div class="sat-date">
            <label for=${`${id}-date`}>Pass date <span class="muted">(UTC)</span></label>
            <input type="date" id=${`${id}-date`} min=${GIBS_EARLIEST} max=${today}
                   value=${imagery.date}
                   onChange=${(e) => e.target.value && setImagery({ date: e.target.value })} />
            ${imagery.date !== utcYesterday() && html`
              <button type="button" class="link" onClick=${() =>
                setImagery({ date: utcYesterday() })}>Yesterday</button>`}
          </div>
          <p class="sat-foot">
            NOAA-20 VIIRS daily composite via NASA GIBS, about 375 m a pixel, so it blurs at
            street zoom. Yesterday by default: today's pass is often still a black wedge. Black
            or blank means no pass yet, not clean air.
          </p>
        </div>`}
    </div>`;
}

/* Which pass is on screen, stamped on the map itself while any satellite layer
   is. A screenshot of the map travels without the panel, and a picture of the
   sky with no date on it invites being read as today's. */
export function SatelliteStamp() {
  const imagery = useImagery();
  if (!anySatellite(imagery)) return null;
  const day = new Date(`${imagery.date}T00:00:00Z`).toLocaleDateString(undefined, {
    day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
  });
  const parts = [
    imagery.base === "satellite" && "true colour",
    imagery.aerosol && "aerosol",
    imagery.fires && "fires",
  ].filter(Boolean);
  return html`
    <p class="sat-stamp" aria-live="polite">
      <strong>VIIRS ${day}</strong>
      <span>${parts.join(" · ")}</span>
    </p>`;
}

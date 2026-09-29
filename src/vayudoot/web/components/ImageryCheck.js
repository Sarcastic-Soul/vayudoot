/* A model's reading of the satellite picture of a hotspot.
 *
 * The only place anyone looks at satellite *imagery* rather than at a
 * satellite's point detections: the server fetches a VIIRS true-colour frame
 * around the hotspot from NASA GIBS and asks the primary-tier model whether a
 * smoke plume is visible and whether cloud is in the way.
 *
 * **It is an annotation, never evidence**, and the panel is built to say so
 * before anything else can be read into it. The picture shown is the exact
 * file the model read, not a fresher tile, so the operator can disagree with
 * it. Everything the model wrote sits under the model mark; the server's
 * disclaimer is shown verbatim in the information blue; and the panel says in
 * words that the reading does not move the hotspot's confidence or its
 * corroboration — `agents/imagery.py` records why that line is drawn there.
 *
 * The hotspot's area is outlined on the picture as a circle at its true
 * radius, scaled from the frame's own bounding box. A circle, never a point:
 * hard constraint 7 holds on a satellite picture exactly as on the map.
 *
 * On load it asks for a cached reading (404 means none), so looking at a
 * hotspot never spends a model call; only the button does.
 */

import { useEffect, useState } from "../vendor/hooks.mjs";
import { html, Fragment } from "../lib/html.js";
import { api, apiUrl } from "../lib/api.js";
import { percent, onDate, atTime, radiusLabel } from "../lib/format.js";
import { Elapsed } from "./HotspotAlert.js";
import { SEVERITY_COLOUR } from "./HotspotsMap.js";
import { EyeIcon, ModelIcon, RetryIcon, SatelliteIcon } from "./Icons.js";

const KM_PER_DEG = 111.32;

/* The layer name as a person would say it. */
function layerLabel(layer) {
  if (!layer) return "";
  const craft = /NOAA20/.test(layer) ? "NOAA-20" : /NOAA21/.test(layer) ? "NOAA-21"
    : /SNPP/.test(layer) ? "Suomi NPP" : "";
  return `${craft ? `${craft} ` : ""}VIIRS true colour`;
}

/* The hotspot's circle on the frame, as fractions of its width and height.
   The frame is EPSG:4326 — longitude and latitude map linearly onto x and y —
   so a kilometre is a different share of the width than of the height. */
function outline(reading, hotspot) {
  const [south, west, north, east] = reading.bbox || [];
  if (![south, west, north, east].every(Number.isFinite) || north <= south || east <= west) {
    return null;
  }
  const lat = hotspot.centre_latitude;
  const lon = hotspot.centre_longitude;
  const widthKm = (east - west) * KM_PER_DEG * Math.cos((lat * Math.PI) / 180);
  const heightKm = (north - south) * KM_PER_DEG;
  return {
    cx: (lon - west) / (east - west),
    cy: (north - lat) / (north - south),
    rx: hotspot.radius_km / widthKm,
    ry: hotspot.radius_km / heightKm,
    widthKm,
  };
}

/* A scale bar a round number of kilometres long, about a fifth of the frame. */
function scaleBar(widthKm) {
  const target = widthKm / 5;
  const step = [1, 2, 5, 10, 20, 50, 100].find((s) => s >= target) || 100;
  return { km: step, share: step / widthKm };
}

function Snapshot({ reading, hotspot, stamp }) {
  const shape = outline(reading, hotspot);
  const bar = shape ? scaleBar(shape.widthKm) : null;
  /* The ring is the map's ring: same severity colour, same dash when not
     corroborated, same white halo under it so it reads on any sky. */
  const colour = SEVERITY_COLOUR[hotspot.severity] || SEVERITY_COLOUR.moderate;
  const src = apiUrl(`/hotspots/${encodeURIComponent(hotspot.hotspot_id)}/imagery.jpg?d=`
    + `${encodeURIComponent(reading.image_date)}&t=${stamp}`);
  return html`
    <figure class="imagery-frame">
      <div class="imagery-pic">
        <img src=${src} width="512" height="512"
             alt=${`Satellite true-colour image of the area around the hotspot, `
               + `${reading.image_date}. The hotspot's extent is outlined.`} />
        ${shape && html`
          <svg class="imagery-overlay" viewBox="0 0 100 100" preserveAspectRatio="none"
               aria-hidden="true">
            <ellipse cx=${shape.cx * 100} cy=${shape.cy * 100}
                     rx=${Math.max(shape.rx * 100, 0.8)} ry=${Math.max(shape.ry * 100, 0.8)}
                     class="imagery-halo" vector-effect="non-scaling-stroke" />
            <ellipse cx=${shape.cx * 100} cy=${shape.cy * 100}
                     rx=${Math.max(shape.rx * 100, 0.8)} ry=${Math.max(shape.ry * 100, 0.8)}
                     class=${`imagery-ring${hotspot.corroborated ? "" : " is-dashed"}`}
                     style=${`stroke:${colour};fill:${colour}2e`}
                     vector-effect="non-scaling-stroke" />
          </svg>`}
        ${shape && html`
          <span class="imagery-tag" style=${`left:${Math.min(shape.cx * 100 + shape.rx * 100
            + 2, 70)}%;top:${shape.cy * 100}%`}>
            Hotspot area, ${radiusLabel(hotspot.radius_km)} radius</span>`}
        ${bar && html`
          <span class="imagery-scale" style=${`width:${bar.share * 100}%`}>
            <span class="tnum">${bar.km} km</span></span>`}
        <span class="imagery-north" aria-hidden="true">N ↑</span>
      </div>
      <figcaption>
        The exact picture the model read: ${layerLabel(reading.layer)}, pass of
        ${" "}${reading.image_date} (UTC), about ${Math.round(shape ? shape.widthKm : 50)} km
        across. North is up.
      </figcaption>
    </figure>`;
}

function Verdict({ label, yes, yesText, noText, tone }) {
  return html`
    <div class=${`imagery-verdict${yes ? ` is-${tone}` : ""}`}>
      <span class="figure-label">${label}</span>
      <strong>${yes ? yesText : noText}</strong>
    </div>`;
}

function Reading({ reading, hotspot, stamp }) {
  const read = Date.parse(reading.read_at);
  return html`
    <${Fragment}>
      <${Snapshot} reading=${reading} hotspot=${hotspot} stamp=${stamp} />
      <div class="imagery-verdicts">
        <${Verdict} label="Smoke plume" yes=${reading.plume_visible} tone="plume"
                    yesText="Visible" noText="Not visible" />
        <${Verdict} label="Cloud over the centre" yes=${reading.cloud_obscured} tone="cloud"
                    yesText="Yes — ground hidden" noText="Clear" />
        <div class="imagery-verdict">
          <span class="figure-label">Model confidence</span>
          <strong class="tnum">${percent(reading.confidence)}</strong>
        </div>
      </div>
      ${reading.cloud_obscured && !reading.plume_visible && html`
        <p class="imagery-cloudnote">Cloud over the centre means the picture cannot answer
          the question. "Not visible" here is not "no smoke".</p>`}
      <blockquote class="imagery-says">
        <span class="model-mark"><${ModelIcon} />What the model says it sees</span>
        <p>${reading.description}</p>
      </blockquote>
      <aside class="disclaimer imagery-disclaimer">
        <${ModelIcon} />
        <div>
          <strong>An annotation, not a measurement</strong>
          <p>${reading.disclaimer}</p>
          <p class="imagery-nochange">This hotspot's confidence and corroboration are exactly
            what they were before the picture was read.</p>
        </div>
      </aside>
      <p class="imagery-meta tnum">
        Read ${Number.isNaN(read) ? "" : `${onDate(reading.read_at)}, ${atTime(read)}`}
        ${" "}· ${reading.layer}
      </p>
    <//>`;
}

export function ImageryCheck({ hotspot }) {
  const id = hotspot.hotspot_id;
  const [reading, setReading] = useState(undefined);   // undefined: still asking
  const [busy, setBusy] = useState(false);
  const [startedAt, setStartedAt] = useState(0);
  const [failure, setFailure] = useState(null);
  const [stamp, setStamp] = useState(0);

  useEffect(() => {
    let live = true;
    api(`/hotspots/${encodeURIComponent(id)}/imagery`)
      .then((found) => { if (live) setReading(found); })
      .catch(() => { if (live) setReading(null); });
    return () => { live = false; };
  }, [id]);

  async function check() {
    setBusy(true);
    setStartedAt(Date.now());
    setFailure(null);
    try {
      setReading(await api(`/hotspots/${encodeURIComponent(id)}/imagery`, { method: "POST" }));
      setStamp(Date.now());
    } catch (error) {
      setFailure({ status: error.status, message: error.message });
    } finally {
      setBusy(false);
    }
  }

  const busyModel = failure && (failure.status === 503 || failure.status === 429);

  return html`
    <section class="imagery-card" aria-labelledby="imagery-heading">
      <div class="alert-card-head">
        <span class="alert-glyph is-model" aria-hidden="true"><${EyeIcon} /></span>
        <div>
          <p class="eyebrow">Satellite imagery</p>
          <h3 id="imagery-heading">
            ${reading ? "What the picture shows" : "Check the satellite picture"}</h3>
        </div>
      </div>

      ${reading === undefined && html`
        <div class="skeleton" style="aspect-ratio:1;width:100%;max-width:420px"></div>`}

      ${reading === null && !busy && html`
        <${Fragment}>
          <p class="alert-why">
            Fetches the latest VIIRS true-colour pass of a ~50 km square around this hotspot
            from NASA GIBS, and asks a model whether a smoke plume is visible and whether cloud
            is in the way. One model call. <strong>An annotation for you, not evidence</strong>:
            it cannot change this hotspot's confidence.
          </p>
          <button type="button" class="secondary imagery-go" onClick=${check}>
            <${SatelliteIcon} /> Check satellite imagery
          </button>
        <//>`}

      ${busy && html`
        <div class="alert-pending" aria-busy="true">
          <p class="visually-hidden" role="status">Fetching and reading the satellite picture.
            This can take up to a minute.</p>
          <span class="pending-spark" aria-hidden="true"><${ModelIcon} /></span>
          <ol>
            <li>Fetching the most recent complete pass from NASA GIBS</li>
            <li>Asking the model what it sees — one primary-tier call</li>
          </ol>
          <span class="pending-clock" aria-hidden="true"><${Elapsed} since=${startedAt} /></span>
        </div>`}

      ${reading && html`<${Reading} reading=${reading} hotspot=${hotspot} stamp=${stamp} />`}

      ${reading && !busy && html`
        <button type="button" class="quiet imagery-again" onClick=${check}
                title="Spends a model call only if a newer pass exists">
          <${RetryIcon} /> Look for a newer pass
        </button>`}

      ${failure && html`
        <div class=${`alert-failure${busyModel || failure.status === 502 ? " is-limit" : ""}`}
             role="alert">
          <p><strong>${failure.status === 502 ? "No usable picture."
            : busyModel ? "The model could not answer right now." : "That did not go through."}
            </strong>${" "}${failure.message}</p>
          <p class="alert-failure-hint">
            ${failure.status === 502
              ? "Usually the pass has not been processed yet, or the frame is mostly an empty "
                + "swath. Nothing was spent on the model."
              : busyModel
                ? "The free-tier model is busy or over its quota. Nothing was saved; trying "
                  + "again in a minute usually works."
                : "Nothing was saved."}
          </p>
          <div class="alert-failure-actions">
            <button type="button" class="secondary" onClick=${check}>
              <${RetryIcon} /> Try again
            </button>
          </div>
        </div>`}
    </section>`;
}

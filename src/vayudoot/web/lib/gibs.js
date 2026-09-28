/* NASA GIBS satellite layers for the hotspot maps, and the one choice of them
 * every map shares.
 *
 * The circles on the map are this system's claims; these layers are the sky
 * they were made about. Putting yesterday's true-colour pass, the aerosol it
 * saw and the fires it recorded under the circles lets an operator check a
 * hotspot against the instrument with their own eyes, without an account, a
 * key or a second tab. GIBS serves all of it keyless and CORS-open.
 *
 * Every identifier, tile matrix set and file extension below was read from the
 * live GetCapabilities documents, not remembered (checked 2026-09-28):
 *
 *   WMTS https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/wmts.cgi
 *   WMS  https://gibs.earthdata.nasa.gov/wms/epsg3857/best/wms.cgi
 *
 * - True colour is `VIIRS_NOAA20_CorrectedReflectance_TrueColor`, JPEG, on
 *   `GoogleMapsCompatible_Level9` — so its native tiles stop at zoom 9 and
 *   Leaflet upsamples past that. NOAA-20 rather than Suomi NPP because SNPP's
 *   daily record has gaps through 2026 and NOAA-20's runs unbroken since 2022,
 *   so an older date in the picker still draws something. Same instrument.
 * - Aerosol optical depth is `VIIRS_NOAA20_AOD_Deep_Blue_Land_Ocean`, PNG, on
 *   `GoogleMapsCompatible_Level6`. Deep Blue rather than Dark Target because it
 *   retrieves over bright land, which is what the Indo-Gangetic plain is in the
 *   dry season. AOD is how much the whole air column dims sunlight: haze, not a
 *   PM2.5 reading, and the panel says so.
 * - Fires are `VIIRS_NOAA20_Thermal_Anomalies_375m_All`. On the WMTS endpoint
 *   that layer is published *only* as Mapbox vector tiles, which Leaflet cannot
 *   draw without a plugin this project will not vendor. The WMS endpoint
 *   rasterises the same layer to PNG on request, and `L.tileLayer.wms` is core
 *   Leaflet — so fires come from WMS and the other two from WMTS.
 * - Borders, coastlines and roads over the imagery are `Reference_Features_15m`,
 *   which has no time dimension, so its template has no date segment. Not
 *   `Reference_Labels_15m`: checked tile by tile it answers most zooms over
 *   India with an opaque black placeholder or a 500, which blacked out the map.
 *   Features does the same over open sea at high zoom, so every PNG overlay
 *   goes through `hideBlankTiles`.
 *
 * The default date is yesterday in UTC: a daily composite is assembled as the
 * passes come in, and today's is usually a black wedge until the afternoon
 * orbit lands.
 */

import { useEffect, useState } from "../vendor/hooks.mjs";

const WMTS = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best";
const WMS = "https://gibs.earthdata.nasa.gov/wms/epsg3857/best/wms.cgi";

export const GIBS_ATTRIBUTION =
  '<a href="https://earthdata.nasa.gov/gibs" target="_blank" rel="noopener">NASA GIBS / EOSDIS</a>';

/* The earliest day all three layers have unbroken daily coverage from — the
   latest start among their GetCapabilities time ranges (fires: 2025-12-23). */
export const GIBS_EARLIEST = "2025-12-23";

const dayISO = (ms) => new Date(ms).toISOString().slice(0, 10);

export const utcToday = () => dayISO(Date.now());
export const utcYesterday = () => dayISO(Date.now() - 86400000);

export const TRUE_COLOUR = {
  id: "VIIRS_NOAA20_CorrectedReflectance_TrueColor",
  label: "True colour",
  tms: "GoogleMapsCompatible_Level9",
  native: 9,
  ext: "jpeg",
};

export const AEROSOL = {
  id: "VIIRS_NOAA20_AOD_Deep_Blue_Land_Ocean",
  label: "Aerosol optical depth",
  tms: "GoogleMapsCompatible_Level6",
  native: 6,
  ext: "png",
  legend: "https://gibs.earthdata.nasa.gov/legends/MODIS_VIIRS_AOD_H.svg",
};

export const FIRES = {
  id: "VIIRS_NOAA20_Thermal_Anomalies_375m_All",
  label: "Fires (thermal anomalies)",
};

const REFERENCE = {
  id: "Reference_Features_15m",
  tms: "GoogleMapsCompatible_Level13",
  native: 13,
};

const wmtsUrl = (layer, date) =>
  `${WMTS}/${layer.id}/default/${date}/${layer.tms}/{z}/{y}/{x}.${layer.ext}`;

/* GIBS answers a tile it has nothing for with a 921-byte PNG that is opaque
   black, not transparent, with a 200. On an overlay that paints a black square
   over the imagery. A tile that is black and opaque all over is hidden; one
   with any transparent or coloured pixel is drawn. Reading pixels needs the
   tile fetched with CORS, which GIBS allows; if a browser refuses anyway the
   tile is left as it is. */
function hideBlankTiles(layer) {
  layer.on("tileload", ({ tile }) => {
    try {
      const canvas = document.createElement("canvas");
      canvas.width = 8;
      canvas.height = 8;
      const context = canvas.getContext("2d", { willReadFrequently: true });
      context.drawImage(tile, 0, 0, 8, 8);
      const pixels = context.getImageData(0, 0, 8, 8).data;
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i] || pixels[i + 1] || pixels[i + 2] || pixels[i + 3] !== 255) return;
      }
      tile.style.visibility = "hidden";
    } catch { /* a tainted canvas: draw the tile as it came */ }
  });
  return layer;
}

/* Built once per map. Returns the layers and a `date` setter that moves the
   dated ones to another day without rebuilding them. */
export function buildGibsLayers(date) {
  const L = window.L;
  const trueColour = L.tileLayer(wmtsUrl(TRUE_COLOUR, date), {
    maxNativeZoom: TRUE_COLOUR.native,
    maxZoom: 19,
    attribution: GIBS_ATTRIBUTION,
    className: "gibs-tiles",
  });
  const reference = hideBlankTiles(L.tileLayer(
    `${WMTS}/${REFERENCE.id}/default/${REFERENCE.tms}/{z}/{y}/{x}.png`,
    {
      maxNativeZoom: REFERENCE.native,
      maxZoom: 19,
      opacity: 0.7,
      crossOrigin: "anonymous",
      attribution: GIBS_ATTRIBUTION,
    },
  ));
  const aerosol = hideBlankTiles(L.tileLayer(wmtsUrl(AEROSOL, date), {
    maxNativeZoom: AEROSOL.native,
    maxZoom: 19,
    opacity: 0.62,
    crossOrigin: "anonymous",
    attribution: GIBS_ATTRIBUTION,
    className: "gibs-tiles",
  }));
  // Unknown options become WMS parameters in Leaflet; `uppercase` sends them
  // as TIME rather than time, which is the spelling the WMS spec uses.
  const fires = L.tileLayer.wms(WMS, {
    layers: FIRES.id,
    format: "image/png",
    transparent: true,
    version: "1.3.0",
    uppercase: true,
    time: date,
    maxZoom: 19,
    attribution: GIBS_ATTRIBUTION,
  });
  return {
    trueColour, reference, aerosol, fires,
    setDate(day) {
      trueColour.setUrl(wmtsUrl(TRUE_COLOUR, day));
      aerosol.setUrl(wmtsUrl(AEROSOL, day));
      fires.setParams({ time: day });   // same key as built, or it is sent twice
    },
  };
}

/* ── the shared choice ──────────────────────────────────────────────────
 *
 * One selection for every hotspot map, so an operator who turns fires on in
 * the operations view still has them when they open a hotspot. Remembered in
 * localStorage as a per-viewer convenience, with every access guarded: private
 * windows throw, and the map must draw either way. The date is not remembered
 * — yesterday is only yesterday for a day. */

const KEY = "vayudoot.gibs";

function recall() {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) || "{}");
    return {
      base: saved.base === "satellite" ? "satellite" : "street",
      aerosol: Boolean(saved.aerosol),
      fires: Boolean(saved.fires),
    };
  } catch {
    return { base: "street", aerosol: false, fires: false };
  }
}

let current = { ...recall(), date: utcYesterday() };
const listeners = new Set();

export function setImagery(patch) {
  current = { ...current, ...patch };
  try {
    const { base, aerosol, fires } = current;
    localStorage.setItem(KEY, JSON.stringify({ base, aerosol, fires }));
  } catch { /* a convenience, not state */ }
  for (const listener of listeners) listener(current);
}

export function useImagery() {
  const [state, setState] = useState(current);
  useEffect(() => {
    listeners.add(setState);
    setState(current);
    return () => listeners.delete(setState);
  }, []);
  return state;
}

export const anySatellite = (s) => s.base === "satellite" || s.aerosol || s.fires;

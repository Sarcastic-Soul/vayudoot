/* Vayudoot interface.
 *
 * A pipeline run is minutes of model calls, so the browser never waits on the
 * submission. It posts the report, gets a case id back, and then polls the case
 * while the stages advance. Everything on screen comes from the case object;
 * there is no second source of truth in the client.
 */

const $ = (id) => document.getElementById(id);
const api = (path, opts) => fetch(path, opts).then(async (r) => {
  if (!r.ok) {
    const body = await r.text();
    let detail = body;
    try { detail = JSON.parse(body).detail ?? body; } catch { /* plain text */ }
    throw new Error(detail || `${r.status} ${r.statusText}`);
  }
  return r.headers.get("content-type")?.includes("json") ? r.json() : r.text();
});

const STAGES = [
  { key: "evidence", title: "Evidence", blurb: "Reading the photograph" },
  { key: "corroboration", title: "Corroboration", blurb: "Satellite, ground stations, wind" },
  { key: "jurisdiction", title: "Jurisdiction", blurb: "Who is responsible for this location" },
  { key: "drafting", title: "Drafting", blurb: "Writing the formal complaint" },
];
const STAGE_INDEX = { received: 0, evidence: 0, corroboration: 1, jurisdiction: 2, drafting: 3,
                      complete: 4, halted: 4 };

/* A run is over when the pipeline reached the end, halted at the confidence
 * floor, or failed. A failed case keeps the stage it died on. */
const isFinished = (c) => c.stage === "complete" || c.stage === "halted" || c.status === "failed";

const state = { case: null, poll: null, lang: "en", pickMap: null, pickMarker: null, casesMap: null };

/* ── views ─────────────────────────────────────────────────────────────── */

function show(view) {
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("is-active", v.id === `view-${view}`));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("is-active", t.dataset.view === view));
  if (view === "cases") loadCases();
  if (view !== "case") stopPolling();
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => show(tab.dataset.view));
});
$("case-back").addEventListener("click", () => show("cases"));

/* ── report form ───────────────────────────────────────────────────────── */

$("photo-drop").addEventListener("click", () => $("photo").click());

$("photo").addEventListener("change", () => {
  const file = $("photo").files[0];
  if (!file) return;
  const preview = $("photo-preview");
  preview.src = URL.createObjectURL(file);
  preview.hidden = false;
  $("photo-hint").hidden = true;
});

$("locate").addEventListener("click", () => {
  if (!navigator.geolocation) {
    $("geo-status").textContent = "This browser will not share a location. Enter coordinates by hand.";
    return;
  }
  $("geo-status").textContent = "Locating…";
  navigator.geolocation.getCurrentPosition(
    ({ coords }) => {
      $("latitude").value = coords.latitude.toFixed(6);
      $("longitude").value = coords.longitude.toFixed(6);
      $("geo-status").textContent = `Located to about ${Math.round(coords.accuracy)} m. Drag the pin if the source is elsewhere.`;
      showPickMap(coords.latitude, coords.longitude);
    },
    (err) => { $("geo-status").textContent = `Could not get a location: ${err.message}`; },
    { enableHighAccuracy: true, timeout: 15000 },
  );
});

function showPickMap(lat, lon) {
  if (!window.L) return;
  const el = $("pick-map");
  el.hidden = false;
  if (!state.pickMap) {
    state.pickMap = L.map(el).setView([lat, lon], 16);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "© OpenStreetMap",
    }).addTo(state.pickMap);
    state.pickMarker = L.marker([lat, lon], { draggable: true }).addTo(state.pickMap);
    state.pickMarker.on("dragend", () => {
      const { lat: y, lng: x } = state.pickMarker.getLatLng();
      $("latitude").value = y.toFixed(6);
      $("longitude").value = x.toFixed(6);
    });
  } else {
    state.pickMap.setView([lat, lon], 16);
    state.pickMarker.setLatLng([lat, lon]);
  }
  setTimeout(() => state.pickMap.invalidateSize(), 50);
}

$("report-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const err = $("form-error");
  err.hidden = true;

  const lat = parseFloat($("latitude").value);
  const lon = parseFloat($("longitude").value);
  if (Number.isNaN(lat) || Number.isNaN(lon)) {
    err.textContent = "Coordinates are required: they decide which authority receives this.";
    err.hidden = false;
    return;
  }

  const body = new FormData();
  body.append("latitude", lat);
  body.append("longitude", lon);
  body.append("note", $("note").value);
  body.append("contact", $("contact").value);
  if ($("photo").files[0]) body.append("image", $("photo").files[0]);

  const button = $("submit");
  button.disabled = true;
  button.textContent = "Starting the case…";
  try {
    const created = await api("/reports", { method: "POST", body });
    openCase(created.case_id);
  } catch (e) {
    err.textContent = e.message;
    err.hidden = false;
  } finally {
    button.disabled = false;
    button.textContent = "Run the case";
  }
});

/* ── case view ─────────────────────────────────────────────────────────── */

function openCase(caseId) {
  show("case");
  $("case-id").textContent = caseId;
  $("timeline").innerHTML = "";
  $("complaint").hidden = true;
  $("envelope-box").hidden = true;
  $("case-photo").hidden = true;
  state.lang = "en";
  refresh(caseId);
  startPolling(caseId);
}

function startPolling(caseId) {
  stopPolling();
  state.poll = setInterval(() => refresh(caseId), 2500);
}

function stopPolling() {
  if (state.poll) clearInterval(state.poll);
  state.poll = null;
}

async function refresh(caseId) {
  let c;
  try {
    c = await api(`/cases/${caseId}`);
  } catch {
    return; // a transient failure while the background run writes the file
  }
  state.case = c;
  render(c);
  if (isFinished(c)) stopPolling();
}

function render(c) {
  $("case-id").textContent = c.case_id;
  const pill = $("case-status");
  pill.textContent = c.status.replace(/_/g, " ");
  pill.dataset.status = c.status;
  $("case-address").textContent = c.address || `${c.report.latitude}, ${c.report.longitude}`;

  if (c.report.image_path) {
    const photo = $("case-photo");
    if (photo.hidden) photo.src = `/cases/${c.case_id}/photo`;
    photo.hidden = false;
  }

  renderTimeline(c);
  renderComplaint(c);
  renderActions(c);
  $("history").innerHTML = c.history.map((h) => `<li>${escapeHtml(h)}</li>`).join("");
}

function renderTimeline(c) {
  const reached = STAGE_INDEX[c.stage] ?? 0;
  const failed = c.status === "failed";
  const halted = c.stage === "halted";

  $("timeline").innerHTML = STAGES.map((stage, i) => {
    let stateName = "pending";
    if (i < reached) stateName = "done";
    else if (i > reached) stateName = "pending";
    else if (failed) stateName = "failed";
    else if (halted || c.stage === "complete") stateName = "done";
    else stateName = "active";
    if (halted && i > 0) stateName = "pending";

    const detail = stageDetail(stage.key, c) ?? (stateName === "active" ? "Working…" : stage.blurb);
    return `<li class="step" data-state="${stateName}">
      <h4>${stage.title}</h4>
      <div class="detail">${detail}</div>
    </li>`;
  }).join("");

  if (failed && c.error) {
    $("timeline").insertAdjacentHTML("beforeend",
      `<li class="step" data-state="failed"><h4>Run failed</h4>
       <div class="detail">${escapeHtml(c.error)}</div></li>`);
  }
}

function stageDetail(key, c) {
  if (key === "evidence" && c.evidence) {
    const e = c.evidence;
    const halted = c.status === "rejected";
    return dl({
      "Classified": `${e.pollution_type.replace(/_/g, " ")} — ${e.severity}`,
      "Confidence": `${(e.confidence * 100).toFixed(0)}%${halted ? " — below the floor, halted for human review" : ""}`,
      "Visible": e.visible_indicators.join(", ") || "none recorded",
    });
  }
  if (key === "corroboration" && c.corroboration) {
    const k = c.corroboration;
    return dl({
      "Independent evidence": k.corroborated ? "corroborated" : "not corroborated",
      "Satellite": `${k.satellite_fire_detections} detection(s). ${k.satellite_summary || ""}`,
      "Air quality": k.air_quality_summary || "no reading",
      "Wind": k.wind_speed_ms == null ? "no reading"
        : `${k.wind_speed_ms} m/s from ${k.wind_from_degrees}°`,
      "Upwind source": k.upwind_source_latitude == null ? "not back-traced"
        : `${k.upwind_source_latitude}, ${k.upwind_source_longitude}`,
      "Notes": k.corroboration_notes || "—",
    });
  }
  if (key === "jurisdiction" && c.jurisdiction) {
    const j = c.jurisdiction;
    return dl({
      "Authority": `${j.authority_name} (${j.authority_tier})`,
      "Statute": `${j.statute}${j.section ? ` — ${j.section}` : ""}`,
      "Response window": `${j.response_window_days} days`,
      "Escalates to": j.escalation_authority || "—",
    });
  }
  if (key === "drafting" && c.complaint) return escapeHtml(c.complaint.subject);
  return null;
}

function dl(pairs) {
  const rows = Object.entries(pairs)
    .map(([k, v]) => `<dt>${escapeHtml(k)}</dt><dd>${escapeHtml(String(v))}</dd>`)
    .join("");
  return `<dl>${rows}</dl>`;
}

function renderComplaint(c) {
  if (!c.complaint) { $("complaint").hidden = true; return; }
  $("complaint").hidden = false;
  $("complaint-subject").textContent = c.complaint.subject;
  $("complaint-statutes").textContent = c.complaint.cited_statutes.length
    ? `Cited: ${c.complaint.cited_statutes.join("; ")}` : "";

  const toggle = $("lang-toggle");
  const hasLocal = Boolean(c.complaint.body_local);
  toggle.hidden = !hasLocal;
  if (hasLocal) $("lang-local").textContent = c.complaint.local_language || "Local language";
  if (!hasLocal) state.lang = "en";

  $("complaint-body").textContent = state.lang === "local" ? c.complaint.body_local : c.complaint.body_en;
  toggle.querySelectorAll("button").forEach((b) => b.classList.toggle("is-active", b.dataset.lang === state.lang));
}

$("lang-toggle").addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  state.lang = button.dataset.lang;
  renderComplaint(state.case);
});

function renderActions(c) {
  const box = $("case-actions");
  box.innerHTML = "";

  if (c.status === "awaiting_confirmation") {
    box.insertAdjacentHTML("beforeend",
      `<button type="button" class="primary" id="confirm">Confirm and file this complaint</button>
       <p class="help">Filing writes to the local sandbox outbox. No authority is contacted.</p>`);
    $("confirm").addEventListener("click", () => act(c.case_id, "confirm", $("confirm")));
  }

  if (c.status === "filed" || c.status === "escalated") loadEnvelope(c.case_id);
}

async function act(caseId, path, button) {
  button.disabled = true;
  button.textContent = "Filing…";
  try {
    render(await api(`/cases/${caseId}/${path}`, { method: "POST" }));
  } catch (e) {
    button.disabled = false;
    button.textContent = `Failed: ${e.message}`;
  }
}

async function loadEnvelope(caseId) {
  try {
    $("envelope").textContent = await api(`/cases/${caseId}/envelope`);
    $("envelope-box").hidden = false;
    $("envelope-box").open = true;
  } catch { /* nothing filed yet */ }
}

/* ── case list and map ─────────────────────────────────────────────────── */

async function loadCases() {
  let cases = [];
  try { cases = await api("/cases"); } catch { /* leave the list empty */ }

  $("cases-empty").hidden = cases.length > 0;
  $("case-list").innerHTML = cases.map((c) => `
    <li><button type="button" data-case="${c.case_id}">
      <span class="row"><strong>${c.case_id}</strong>
        <span class="pill" data-status="${c.status}">${c.status.replace(/_/g, " ")}</span></span>
      <span class="where">${escapeHtml(c.address || `${c.report.latitude}, ${c.report.longitude}`)}</span>
      <span class="where">${c.evidence ? escapeHtml(c.evidence.pollution_type.replace(/_/g, " ")) : "classifying…"}</span>
    </button></li>`).join("");

  $("case-list").querySelectorAll("button").forEach((b) => {
    b.addEventListener("click", () => openCase(b.dataset.case));
  });

  drawCasesMap(cases);
}

function drawCasesMap(cases) {
  if (!window.L) return;
  if (!state.casesMap) {
    state.casesMap = L.map($("cases-map")).setView([22.35, 78.66], 4);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "© OpenStreetMap",
    }).addTo(state.casesMap);
    state.caseLayer = L.layerGroup().addTo(state.casesMap);
  }
  state.caseLayer.clearLayers();

  const points = [];
  cases.forEach((c) => {
    const point = [c.report.latitude, c.report.longitude];
    points.push(point);
    L.marker(point)
      .bindPopup(`<strong>${c.case_id}</strong><br>${escapeHtml(c.status.replace(/_/g, " "))}`)
      .on("click", () => openCase(c.case_id))
      .addTo(state.caseLayer);
  });

  if (points.length) state.casesMap.fitBounds(points, { maxZoom: 13, padding: [24, 24] });
  setTimeout(() => state.casesMap.invalidateSize(), 50);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
  ));
}

/* Deep link: /#VD-XXXXXXXX opens that case directly. */
if (location.hash.length > 1) openCase(location.hash.slice(1));

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

const state = { case: null, poll: null, lang: "en", pickMap: null, pickMarker: null,
                casesMap: null, coverage: null };

/* ── views ─────────────────────────────────────────────────────────────── */

function show(view) {
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("is-active", v.id === `view-${view}`));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("is-active", t.dataset.view === view));
  if (view === "cases") loadCases();
  if (view === "coverage") loadCoverage();
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

/* Location.
 *
 * A coordinate is not a human unit. The pin is the interface: it exists from the
 * moment the page loads, geolocation moves it if the citizen allows that, a
 * place search moves it if they do not, and dragging it is always available. The
 * latitude and longitude are hidden fields that the map writes into, and the
 * address underneath is what the citizen actually reads back.
 */

const INDIA_CENTRE = [22.35, 79.0];

function setPoint(lat, lon, { zoom = 16, describe = true } = {}) {
  $("latitude").value = lat.toFixed(6);
  $("longitude").value = lon.toFixed(6);
  if (state.pickMap) {
    state.pickMap.setView([lat, lon], zoom);
    state.pickMarker.setLatLng([lat, lon]);
  }
  if (describe) describePoint(lat, lon);
}

let describeToken = 0;
async function describePoint(lat, lon) {
  const token = ++describeToken;
  const out = $("picked-address");
  out.textContent = "Finding the address…";
  out.classList.add("is-loading");
  try {
    const geo = await api(`/geocode?lat=${lat}&lon=${lon}`);
    if (token !== describeToken) return;
    out.textContent = geo.display_name || `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
  } catch {
    if (token !== describeToken) return;
    out.textContent = `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
  } finally {
    if (token === describeToken) out.classList.remove("is-loading");
  }
}

function initPickMap() {
  if (!window.L || state.pickMap) return;
  state.pickMap = L.map($("pick-map")).setView(INDIA_CENTRE, 4);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "© OpenStreetMap",
  }).addTo(state.pickMap);
  state.pickMarker = L.marker(INDIA_CENTRE, { draggable: true }).addTo(state.pickMap);

  state.pickMarker.on("dragend", () => {
    const { lat, lng } = state.pickMarker.getLatLng();
    setPoint(lat, lng, { zoom: state.pickMap.getZoom() });
  });
  // Tapping the map is faster than dragging on a phone.
  state.pickMap.on("click", (e) => setPoint(e.latlng.lat, e.latlng.lng, { zoom: state.pickMap.getZoom() }));

  locate({ quiet: true });
}

function locate({ quiet = false } = {}) {
  const out = $("picked-address");
  if (!navigator.geolocation) {
    if (!quiet) out.textContent = "This browser will not share a location. Search or drag the pin.";
    return;
  }
  if (!quiet) out.textContent = "Locating…";
  navigator.geolocation.getCurrentPosition(
    ({ coords }) => setPoint(coords.latitude, coords.longitude),
    (err) => {
      if (!quiet) out.textContent = `Could not get a location: ${err.message}. Search or drag the pin.`;
    },
    { enableHighAccuracy: true, timeout: 15000 },
  );
}

$("locate").addEventListener("click", () => locate());

/* Place search. Nominatim asks for at most one request a second, so this waits
 * for a pause in typing rather than firing on every keystroke. */
let searchTimer = null;
$("place").addEventListener("input", () => {
  clearTimeout(searchTimer);
  const query = $("place").value.trim();
  if (query.length < 3) {
    $("place-results").hidden = true;
    return;
  }
  searchTimer = setTimeout(() => runSearch(query), 450);
});

async function runSearch(query) {
  const list = $("place-results");
  try {
    const { results } = await api(`/geocode?q=${encodeURIComponent(query)}`);
    const usable = (results || []).filter((r) => !r.error);
    if (!usable.length) {
      list.innerHTML = '<li class="muted">Nothing found</li>';
      list.hidden = false;
      return;
    }
    list.innerHTML = usable
      .map((r, i) => `<li><button type="button" data-i="${i}">${escapeHtml(r.display_name)}</button></li>`)
      .join("");
    list.hidden = false;
    list.querySelectorAll("button").forEach((button) => {
      button.addEventListener("click", () => {
        const hit = usable[Number(button.dataset.i)];
        setPoint(hit.latitude, hit.longitude);
        $("place").value = "";
        list.hidden = true;
      });
    });
  } catch {
    list.hidden = true;
  }
}

document.addEventListener("click", (e) => {
  if (!e.target.closest(".place-search")) $("place-results").hidden = true;
});

$("report-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const err = $("form-error");
  err.hidden = true;

  const lat = parseFloat($("latitude").value);
  const lon = parseFloat($("longitude").value);
  if (Number.isNaN(lat) || Number.isNaN(lon)) {
    err.textContent = "Place the pin first: it decides which authority receives this.";
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

  renderCoverage(c);
  renderTimeline(c);
  renderComplaint(c);
  renderActions(c);
  $("history").innerHTML = c.history.map((h) => `<li>${escapeHtml(h)}</li>`).join("");
}

/* An authority the table did not actually have must not read like one it did. */
function renderCoverage(c) {
  const box = $("coverage-warning");
  const coverage = c.jurisdiction?.coverage;
  if (!c.jurisdiction || !coverage || coverage === "exact") {
    box.hidden = true;
    return;
  }
  const headline = coverage === "generic"
    ? "This region is not in the authority table."
    : "No local authority for this city is in the table.";
  const note = c.jurisdiction.coverage_note
    || "The complaint resolved to a broader authority than the statute names.";
  box.innerHTML = `<strong>${escapeHtml(headline)}</strong> ${escapeHtml(note)} `
    + `<button type="button" class="link" data-goto-coverage>See what is covered</button>`;
  box.dataset.coverage = coverage;
  box.hidden = false;
  box.querySelector("[data-goto-coverage]").addEventListener("click", () => show("coverage"));
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

/* ── coverage ───────────────────────────────────────────────────────────
 *
 * Jurisdiction comes from a fixed table, so the table's edges are the system's
 * edges. Publishing them is the honest move: a citizen can see in advance
 * whether their region resolves to a named authority or to a placeholder.
 */

async function loadCoverage() {
  if (state.coverage) return renderCoverageTable();
  try {
    state.coverage = await api("/authorities");
    renderCoverageTable();
  } catch (e) {
    $("coverage-list").innerHTML = `<li class="muted">Could not load the table: ${escapeHtml(e.message)}</li>`;
  }
}

function renderCoverageTable() {
  const data = state.coverage;
  $("coverage-placeholder-note").hidden = !data.addresses_are_placeholders;
  $("coverage-counts").textContent =
    `${data.region_count} states and union territories, ${data.municipal_count} municipal bodies.`;

  $("coverage-categories").innerHTML =
    "<thead><tr><th>Pollution type</th><th>Goes to</th><th>Under</th><th>Window</th></tr></thead><tbody>"
    + Object.entries(data.categories)
      .filter(([key]) => key !== "default")
      .map(([key, rule]) => `<tr>
        <td>${escapeHtml(key.replace(/_/g, " "))}</td>
        <td>${escapeHtml(rule.tier)}</td>
        <td>${escapeHtml(rule.statute)}${rule.section ? `<span class="muted"> — ${escapeHtml(rule.section)}</span>` : ""}</td>
        <td>${rule.response_window_days} days</td>
      </tr>`).join("")
    + "</tbody>";

  drawCoverageList(data.regions);
}

function drawCoverageList(regions) {
  $("coverage-list").innerHTML = regions.map((r) => `
    <li>
      <div class="coverage-region">
        <h3>${escapeHtml(r.region)}</h3>
        <p class="muted">${escapeHtml(r.state_board.name || "—")}
          <span class="addr">${escapeHtml(r.state_board.email || "")}</span></p>
      </div>
      ${r.municipal.length ? `<ul class="coverage-cities">${r.municipal.map((m) => `
        <li><span>${escapeHtml(m.city)}</span>
            <span class="muted">${escapeHtml(m.name)}</span>
            <span class="addr">${escapeHtml(m.email || "")}</span></li>`).join("")}</ul>`
        : `<p class="muted none">No municipal bodies listed — waste and dust complaints here
             resolve to the state board.</p>`}
    </li>`).join("");
}

$("coverage-filter").addEventListener("input", () => {
  if (!state.coverage) return;
  const q = $("coverage-filter").value.trim().toLowerCase();
  const regions = !q ? state.coverage.regions : state.coverage.regions.filter((r) =>
    r.region.toLowerCase().includes(q)
    || r.state_board.name?.toLowerCase().includes(q)
    || r.municipal.some((m) => m.city.toLowerCase().includes(q) || m.name.toLowerCase().includes(q)));
  drawCoverageList(regions);
});

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (ch) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
  ));
}

initPickMap();

/* Deep link: /#VD-XXXXXXXX opens that case directly. */
if (location.hash.length > 1) openCase(location.hash.slice(1));

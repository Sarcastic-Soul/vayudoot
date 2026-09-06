/* One repeat pattern: where it is, how long it has run, and who reported it.
 *
 * A cluster is the one object in this product that is inherently spatial — it
 * is defined by a centre and a radius — so the map is not decoration here. The
 * circle is the group's actual extent, the pins are its members, and the two
 * together are the claim: these reports are the same problem, not reports that
 * happen to share a postcode.
 *
 * There is no `GET /clusters/{id}`: the listing is derived arithmetic over the
 * case store, so this reads the list and finds its own group. That also means a
 * cluster can stop existing — a member withdrawn, a group dropping under the
 * minimum — and the not-found state says so rather than reading as a bad link.
 *
 * The members are listed oldest first and numbered. A record is read forwards,
 * and the number is the thing a complaint quotes: "this is the fourteenth".
 */

import { useEffect, useRef } from "../vendor/hooks.mjs";
import { html, Fragment } from "../lib/html.js";
import { navigate } from "../lib/router.js";
import { useClusters } from "../lib/store.js";
import { words, onDate, extentLabel, spanLabel, whoReported } from "../lib/format.js";
import { TILES, useLeafletMap, INDIA_CENTRE } from "../lib/maps.js";
import { MapPane } from "./MapPane.js";
import { BackIcon, PinIcon, PatternIcon } from "./Icons.js";
import { CaseListSkeleton } from "./Skeletons.js";

/* Chosen against the OpenStreetMap tiles, which are the same light tiles in
   both themes, so these are fixed rather than token-driven. */
const EXTENT = { color: "#1a5296", weight: 2, fillColor: "#1a5296", fillOpacity: 0.08 };
const MEMBER = { radius: 7, color: "#ffffff", weight: 2, fillColor: "#1a5296", fillOpacity: 0.92 };
const CENTRE = { radius: 4, color: "#8a4e07", weight: 2, fillColor: "#8a4e07", fillOpacity: 1 };

/* Leaflet takes innerHTML when handed a string, so the popup is built as real
   nodes. Same reasoning as the case map: escaping should be structural. */
function popupFor(member, index) {
  const box = document.createElement("div");
  const id = document.createElement("strong");
  id.textContent = `${index}. ${member.case_id}`;
  box.append(id, document.createElement("br"), onDate(member.observed_at));
  return box;
}

/* The map is its own component so that it mounts only once there is a cluster
   to draw. `useLeafletMap` builds the map on mount against a ref, so a
   container that is not in the document yet never gets one — which is exactly
   what happened when this lived in the parent and the pane was rendered
   conditionally underneath it. */
function ClusterMap({ cluster }) {
  const layer = useRef(null);

  const [container, map] = useLeafletMap((node) => {
    const created = window.L.map(node).setView(INDIA_CENTRE, 4);
    window.L.tileLayer(TILES.url, TILES.options).addTo(created);
    layer.current = window.L.layerGroup().addTo(created);
    return created;
  });

  useEffect(() => {
    if (!map.current || !cluster || !layer.current) return undefined;
    layer.current.clearLayers();

    const centre = [cluster.centre_latitude, cluster.centre_longitude];
    // A group whose members sit almost on top of each other has a radius of a
    // few metres, which draws as a dot. The floor keeps the extent legible
    // without overstating it — the figure beside the map is the honest one.
    const metres = Math.max(cluster.radius_km * 1000, 60);
    const ring = window.L.circle(centre, { ...EXTENT, radius: metres }).addTo(layer.current);
    window.L.circleMarker(centre, CENTRE)
      .bindPopup("Centre of the group")
      .addTo(layer.current);

    cluster.members.forEach((member, i) => {
      window.L.circleMarker([member.latitude, member.longitude], MEMBER)
        .bindPopup(popupFor(member, i + 1))
        .on("click", () => navigate(member.case_id))
        .addTo(layer.current);
    });

    map.current.fitBounds(ring.getBounds(), { padding: [28, 28], maxZoom: 17 });
    const timer = setTimeout(() => {
      if (!map.current) return;
      map.current.invalidateSize();
      map.current.fitBounds(ring.getBounds(), { padding: [28, 28], maxZoom: 17 });
    }, 60);
    return () => clearTimeout(timer);
  }, [cluster]);

  return html`<${MapPane} paneClass="cluster-map" containerRef=${container} />`;
}

export function ClusterView({ clusterId }) {
  const { data, error } = useClusters();
  const cluster = data ? data.find((c) => c.cluster_id === clusterId) : null;
  const who = cluster ? whoReported(cluster) : null;

  return html`
    <div class="case-head">
      <button type="button" class="link back" onClick=${() => navigate("cases")}>
        <${BackIcon} /> All cases
      </button>
      <h2>${clusterId}</h2>
      ${cluster && html`
        <p class="cluster-lead">
          <${PatternIcon} />
          <span>
            <strong>${cluster.report_count} reports</strong> of
            ${" "}${words(cluster.pollution_type)}, over ${spanLabel(cluster.span_days)},
            within ${extentLabel(cluster.radius_km)} of one another.
          </span>
        </p>`}
      ${cluster && cluster.address && html`
        <p class="case-where"><${PinIcon} /><span>${cluster.address}</span></p>`}
    </div>

    ${!data && !error && html`<${CaseListSkeleton} />`}

    ${error && html`<p class="note is-bad">Could not load the patterns: ${error}</p>`}

    ${data && !cluster && html`
      <div class="empty">
        <${PatternIcon} />
        <h3>No such pattern</h3>
        <p>A pattern is worked out from the cases each time it is asked for, so one can stop
          existing — a report withdrawn, or a group that has dropped back below the number of
          reports it takes to be a pattern at all.</p>
        <button type="button" class="primary" onClick=${() => navigate("cases")}>
          Back to the cases
        </button>
      </div>`}

    ${cluster && html`
      <${Fragment}>
        <${ClusterMap} cluster=${cluster} />

        <div class="cluster-grid">
          <div class="case-col">
            <h3 class="section-label">Who reported this</h3>
            <div class="who-card">
              <p class="who-line">${who.line}</p>
              <p class="who-caveat">${who.caveat}</p>
              <dl class="who-split">
                <div>
                  <dt>Identified contacts</dt>
                  <dd class="tnum">${cluster.distinct_reporters}</dd>
                </div>
                <div>
                  <dt>Anonymous reports</dt>
                  <dd class="tnum">${cluster.anonymous_reports}</dd>
                </div>
              </dl>
            </div>

            <h3 class="section-label">The pattern</h3>
            <dl class="cluster-facts">
              <div><dt>First reported</dt><dd>${onDate(cluster.first_reported_at)}</dd></div>
              <div><dt>Most recent</dt><dd>${onDate(cluster.last_reported_at)}</dd></div>
              <div><dt>Running for</dt><dd>${spanLabel(cluster.span_days)}</dd></div>
              <div><dt>Extent</dt><dd>${extentLabel(cluster.radius_km)} from the centre</dd></div>
              <div>
                <dt>Authority</dt>
                <dd>${cluster.authority_name || "Not resolved on any member yet"}</dd>
              </div>
            </dl>

            <p class="note">
              Membership is worked out from the case store every time this page is opened, not
              stored on the cases. A report that arrives tomorrow within the same place, kind
              and window joins this group, and the count here goes up.
            </p>
          </div>

          <div class="case-col">
            <div class="timeline-head">
              <h3 class="section-label">The reports in it</h3>
              <p class="timeline-progress tnum">${cluster.report_count} in all</p>
            </div>
            <ol class="member-list">
              ${cluster.members.map((member, i) => html`
                <li key=${member.case_id}>
                  <button type="button" onClick=${() => navigate(member.case_id)}>
                    <span class="member-n tnum" aria-hidden="true">${i + 1}</span>
                    <span class="member-body">
                      <span class="row">
                        <strong>${member.case_id}</strong>
                        <span class="pill" data-status=${member.status}>
                          ${words(member.status)}</span>
                      </span>
                      <span class="member-meta">
                        <span>${onDate(member.observed_at)}</span>
                        <span class="tnum">
                          ${member.distance_km < 0.001
                            ? "at the centre"
                            : `${Math.round(member.distance_km * 1000)} m from the centre`}
                        </span>
                      </span>
                    </span>
                  </button>
                </li>`)}
            </ol>
          </div>
        </div>
      <//>`}`;
}

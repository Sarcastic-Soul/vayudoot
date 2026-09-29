/* The network: who this node is, whose feeds it reads, what it publishes, and
 * how it forecasts.
 *
 * Federation here is a shared *detection layer*, plus a published forecaster
 * spec — never shared model weights. A node publishes the hotspots it found on
 * a versioned feed and reads its neighbours', and a neighbour's hotspots are
 * forecasting context only: never republished as ours. `federation.py` and
 * `docs/federation.md` have the reasons.
 *
 * From feed version 1.1 a node also publishes its forecaster: the prompt's
 * hash, the horizon, the upwind reach, the risk bands, the models and its own
 * scored record. The panel compares each neighbour's with ours and says what
 * differs, in words. Two things about that comparison are deliberate:
 *
 *   Bands that differ between countries are by design. Each node anchors "low"
 *   to its own country's air quality standard, so an Indian and a South
 *   African node will never have the same bands, and the panel says so in a
 *   neutral tone rather than flagging it like a fault.
 *
 *   A setting that could be adopted is shown as the environment variable a
 *   person would set — and nothing more. There is no button that applies it.
 *   Changing how this node forecasts is an operator's decision, made on
 *   purpose, not something a neighbour's feed can do.
 *
 * Unreachable is an ordinary state on a federated network, so a neighbour that
 * did not answer is shown with its error rather than hidden, and zero
 * neighbours is said plainly.
 *
 * Flags are drawn (`Flag.js`), never emoji alone, and always beside the ISO
 * code: a flag is decoration, not the label.
 */

import { html } from "../lib/html.js";
import { apiUrl } from "../lib/api.js";
import { useNetwork } from "../lib/store.js";
import {
  countryName, plural, rateText, shortHash, shortWhen,
} from "../lib/format.js";
import { Flag, FlagMark } from "./Flag.js";
import { ModelMark } from "./CorridorOutlook.js";
import { NetworkIcon, FeedIcon, GlobeIcon, OutIcon, ForkIcon } from "./Icons.js";

/* ── the forecaster, and what differs ─────────────────────────────────── */

const num = (v) => (typeof v === "number" ? String(Math.round(v * 10) / 10) : String(v));

/* Where each band's PM2.5 and PM10 ceiling differs, in words: "low up to 40
   µg/m³ PM2.5 (ours 60)". Only the boundaries that differ are named. */
function bandChanges(ours, theirs) {
  const mine = Object.fromEntries((ours || []).map((b) => [b.risk, b]));
  const out = [];
  for (const b of theirs || []) {
    const m = mine[b.risk];
    if (!m) { out.push(`a "${b.risk}" band we do not have`); continue; }
    const bits = [];
    if (b.pm25_to !== m.pm25_to && b.pm25_to != null) {
      bits.push(`${num(b.pm25_to)} µg/m³ PM2.5 (ours ${m.pm25_to == null ? "open"
        : num(m.pm25_to)})`);
    }
    if (b.pm10_to !== m.pm10_to && b.pm10_to != null) {
      bits.push(`${num(b.pm10_to)} PM10 (ours ${m.pm10_to == null ? "open" : num(m.pm10_to)})`);
    }
    if (bits.length) out.push(`${b.risk} up to ${bits.join(", ")}`);
  }
  return out;
}

function describe(diff) {
  switch (diff.field) {
    case "horizon_hours":
      return `Looks ${num(diff.theirs)} hours ahead (ours ${num(diff.ours)})`;
    case "upwind_km":
      return `Reads hotspots up to ${num(diff.theirs)} km upwind (ours ${num(diff.ours)} km)`;
    case "forecaster_version":
      return `Forecaster version ${diff.theirs} (ours ${diff.ours})`;
    case "prompt_sha256":
      return `A different prompt: ${shortHash(diff.theirs)} (ours ${shortHash(diff.ours)})`;
    case "model_ids":
      return `Models ${(diff.theirs || []).join(" → ") || "none named"} (ours ${
        (diff.ours || []).join(" → ") || "none named"})`;
    case "bands": {
      const changes = bandChanges(diff.ours, diff.theirs);
      return `Risk bands: ${changes.length ? changes.join("; ") : "drawn differently"}`;
    }
    default:
      return `${diff.field} differs`;
  }
}

/* A scored record in one line. Null rates are "nothing scored", never 0%. */
function skillLine(skill) {
  if (!skill) return "No scored record published";
  if (!skill.scored) return `No forecast scored yet (last ${skill.window_days} days)`;
  return `${plural(skill.scored, "forecast")} scored · ${rateText(skill.exact_rate)} exact · `
    + `persistence ${rateText(skill.persistence_exact_rate)} · CAMS ${
      rateText(skill.cams_exact_rate)}`;
}

function ThisForecaster({ spec }) {
  if (spec === null) return html`<div class="net-card skeleton net-skeleton"></div>`;
  if (spec === false) {
    return html`<div class="net-card"><p class="muted">This node's forecaster spec could not
      be read.</p></div>`;
  }
  const small = spec.skill && spec.skill.scored > 0 && spec.skill.scored < 30;
  return html`
    <div class="net-card net-forecaster">
      <div class="net-card-head">
        <span class="eyebrow">This node's forecaster</span>
        <${ModelMark}>Model-derived<//>
      </div>
      <dl class="net-facts">
        <div><dt>Version</dt><dd class="tnum">v${spec.forecaster_version}</dd></div>
        <div>
          <dt>Prompt</dt>
          <dd class="mono" title=${spec.prompt_sha256}>${shortHash(spec.prompt_sha256)}…</dd>
        </div>
        <div><dt>Looks ahead</dt><dd class="tnum">${num(spec.horizon_hours)} hours</dd></div>
        <div><dt>Upwind reach</dt><dd class="tnum">${num(spec.upwind_km)} km</dd></div>
        <div>
          <dt>Models</dt>
          <dd>${spec.provider}${spec.tier ? ` · ${spec.tier} tier` : ""}<br />
            <span class="mono fc-models">${(spec.model_ids || []).join(" → ")}</span></dd>
        </div>
        <div><dt>Record</dt><dd>${skillLine(spec.skill)}</dd></div>
      </dl>
      ${small && html`<p class="net-hint">Fewer than 30 scored: anecdote, not evidence.</p>`}
      <p class="net-hint">Published on the feed so a neighbour can see how this node forecasts
        and compare. The spec is shared; nothing about it is applied to anyone.</p>
    </div>`;
}

function PeerForecaster({ n, ownCountry }) {
  const match = n.forecaster_match;
  if (!match) return null;
  if (!match.published) {
    return html`
      <div class="nb-fc">
        <span class="fc-chip is-none">Publishes no forecaster</span>
        <span class="nb-fc-note">Its feed is v${n.feed_version || "1.0"}; the forecaster spec
          arrived in 1.1.</span>
      </div>`;
  }
  const theirCountry = String(n.node?.country || "").toUpperCase();
  const otherCountry = theirCountry && ownCountry && theirCountry !== ownCountry;
  const diffs = match.differences || [];
  const onlyBands = diffs.length > 0 && diffs.every((d) => d.field === "bands");
  const chip = match.same_forecaster
    ? html`<span class="fc-chip is-same">Same forecaster</span>`
    : onlyBands && otherCountry
      ? html`<span class="fc-chip is-national">Same method, national bands</span>`
      : html`<span class="fc-chip is-diff">Different settings</span>`;
  return html`
    <div class="nb-fc">
      ${chip}
      ${diffs.length > 0 && html`
        <ul class="nb-diffs">
          ${diffs.map((d) => html`
            <li key=${d.field}>
              ${describe(d)}
              ${d.field === "bands" && otherCountry && html`
                <span class="nb-design">By design: each node anchors "low" to its own
                  national standard, and ${countryName(theirCountry)}'s is not${" "}
                  ${countryName(ownCountry)}'s.</span>`}
            </li>`)}
        </ul>`}
      ${(match.adoptable || []).length > 0 && html`
        <div class="nb-adopt">
          <span class="nb-adopt-k"><${ForkIcon} /> To match it on this node, an operator would
            set</span>
          ${match.adoptable.map((a) => html`
            <code key=${a.env}>${a.env}=<wbr />${num(a.value)}</code>`)}
          <span class="nb-fc-note">Nothing is applied automatically.</span>
        </div>`}
      <span class="nb-fc-note">Their record: ${skillLine(n.forecaster?.skill)}</span>
    </div>`;
}

function ThisNode({ node, feed }) {
  if (node === null) return html`<div class="net-card skeleton net-skeleton"></div>`;
  if (node === false) {
    return html`<div class="net-card"><p class="muted">This node's identity could not be read.
      </p></div>`;
  }
  const unconfigured = !node.region || node.region === "unspecified";
  return html`
    <div class="net-card net-self">
      <span class="eyebrow">This node</span>
      <div class="self-id">
        <span class="flag self-flag" title=${countryName(node.country) || null}>
          <${FlagMark} code=${node.country} size=${32} />
          <span class="flag-code">${String(node.country || "").toUpperCase() || "—"}</span>
        </span>
        <div>
          <h4>${node.name}</h4>
          <p class="muted">${unconfigured ? "No region set" : node.region}</p>
        </div>
      </div>
      <dl class="net-facts">
        <div><dt>Node id</dt><dd class="mono">${node.node_id}</dd></div>
        <div>
          <dt>Publishing</dt>
          <dd class="tnum">${feed ? plural(feed.hotspot_count, "hotspot")
            : feed === false ? "No feed" : "…"}</dd>
        </div>
        ${feed && html`
          <div><dt>Feed</dt><dd class="tnum">v${feed.feed_version} · ${shortWhen(
            feed.generated_at)}</dd></div>`}
      </dl>
      ${unconfigured && html`
        <p class="net-hint">Not yet named on the network. <code>VAYUDOOT_NODE_NAME</code>,
          <code>_REGION</code> and <code>_COUNTRY</code> give it an identity a neighbour can
          read.</p>`}
    </div>`;
}

function Neighbours({ neighbours, ownCountry }) {
  if (neighbours === null) return html`<div class="net-card skeleton net-skeleton"></div>`;
  if (neighbours === false) {
    return html`<div class="net-card"><p class="muted">The neighbour list could not be read.
      </p></div>`;
  }
  const { configured, reachable, neighbours: list } = neighbours;
  return html`
    <div class="net-card net-neighbours">
      <div class="net-card-head">
        <span class="eyebrow">Neighbours</span>
        <span class="net-count tnum">${configured
          ? `${reachable} of ${configured} reachable` : "none configured"}</span>
      </div>

      ${configured === 0 ? html`
        <div class="net-empty">
          <${NetworkIcon} />
          <p><strong>This node reads nobody's feed yet.</strong> It publishes its own, but no
            neighbour is configured, so its forecasts see only what it detected itself.</p>
          <p class="muted">Adding one is a list of feed URLs in
            <code>VAYUDOOT_NEIGHBOUR_FEEDS</code>. Their hotspots then feed this node's
            forecasts as upwind context — never republished as its own.</p>
        </div>`
      : html`
        <ul class="neighbour-list">
          ${list.map((n) => html`
            <li key=${n.url} class=${n.error ? "is-down" : "is-up"}>
              <span class="nb-dot" aria-hidden="true"></span>
              <div class="nb-main">
                <span class="nb-name">
                  ${n.node ? html`<${Flag} code=${n.node.country} /> ${n.node.name}`
                    : "Unknown node"}
                </span>
                <span class="nb-meta">
                  ${n.error ? "Unreachable" : `Reachable · ${n.node?.region || "no region"}`}
                  <span class="nb-url">${n.url}</span>
                </span>
                ${n.error && html`<span class="nb-error">${n.error}</span>`}
                ${!n.error && html`<${PeerForecaster} n=${n} ownCountry=${ownCountry} />`}
              </div>
              ${!n.error && html`
                <span class="nb-count tnum">${n.hotspot_count}<small>${n.hotspot_count === 1
                  ? "hotspot" : "hotspots"}</small></span>`}
            </li>`)}
        </ul>`}
    </div>`;
}

/* `href` is a path on this node's API, not on whoever served the page, so it
   goes through `apiUrl`; `title` stays the bare path, which is what a
   neighbour node would ask for. */
function FeedLink({ href, Icon, title, format, children }) {
  return html`
    <a class="feed-link" href=${apiUrl(href)} target="_blank" rel="noopener">
      <span class="feed-icon"><${Icon} /></span>
      <span class="feed-text">
        <span class="feed-title"><code>${title}</code><span class="feed-format">${format}</span>
        </span>
        <span class="feed-what">${children}</span>
      </span>
      <${OutIcon} />
    </a>`;
}

export function NetworkPanel() {
  const { node, neighbours, feed, forecaster } = useNetwork();
  const ownCountry = node ? String(node.country || "").toUpperCase() : "";

  return html`
    <section class="network" aria-labelledby="network-title">
      <header class="network-head">
        <span class="network-mark" aria-hidden="true"><${NetworkIcon} /></span>
        <div>
          <h2 id="network-title">The network</h2>
          <p>Smoke does not stop at a state line, or a national one. Each deployment is a node:
            it publishes what it detects on an open feed and reads its neighbours', so a fire
            upwind is in the forecast before the smoke arrives. What is shared is a detection
            layer and a description of how each node forecasts — never trained weights, and
            never a setting pushed from one node to another.</p>
        </div>
      </header>

      <div class="network-grid">
        <div class="network-col">
          <${ThisNode} node=${node} feed=${feed} />
          <${ThisForecaster} spec=${forecaster} />
        </div>
        <${Neighbours} neighbours=${neighbours} ownCountry=${ownCountry} />
      </div>

      <div class="feed-links">
        <${FeedLink} href="/feed" Icon=${FeedIcon} title="/feed" format="JSON · versioned">
          The contract a neighbour node reads: this node's hotspots, with their confidence and
          corroboration flag, and nothing that identifies a reporter.
        <//>
        <${FeedLink} href="/feed.geojson" Icon=${GlobeIcon} title="/feed.geojson"
                     format="GeoJSON · RFC 7946">
          The same feed for any GIS — open it in QGIS, ArcGIS or Google Earth with no code.
          Hotspots are published as areas, never points.
        <//>
      </div>
    </section>`;
}

/* The network: who this node is, whose feeds it reads, and what it publishes.
 *
 * Federation here is a shared *detection layer*, not shared model weights —
 * the honest reading of "share predictive models", said on the panel rather
 * than left for a reader to assume the grander thing. A node publishes the
 * hotspots it found on a versioned feed and reads its neighbours', and a
 * neighbour's hotspots are forecasting context only: never republished as
 * ours. `federation.py` and `docs/federation.md` have the reasons.
 *
 * Unreachable is an ordinary state on a federated network, so a neighbour that
 * did not answer is shown with its error rather than hidden, and zero
 * neighbours is said plainly. A panel that drew a busy network diagram over an
 * instance that reads nobody's feed would be the dishonest version of this.
 *
 * The flag is decoration beside the ISO code, never instead of it: a system
 * without an emoji font renders it as two letters.
 */

import { html } from "../lib/html.js";
import { useNetwork } from "../lib/store.js";
import { flagOf, plural, shortWhen } from "../lib/format.js";
import { NetworkIcon, FeedIcon, GlobeIcon, OutIcon } from "./Icons.js";

function Flag({ code }) {
  const flag = flagOf(code);
  return html`
    <span class="flag">
      ${flag && html`<span class="flag-emoji" aria-hidden="true">${flag}</span>`}
      <span class="flag-code">${String(code || "").toUpperCase() || "—"}</span>
    </span>`;
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
        <${Flag} code=${node.country} />
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

function Neighbours({ neighbours }) {
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
              </div>
              ${!n.error && html`
                <span class="nb-count tnum">${n.hotspot_count}<small>${n.hotspot_count === 1
                  ? "hotspot" : "hotspots"}</small></span>`}
            </li>`)}
        </ul>`}
    </div>`;
}

function FeedLink({ href, Icon, title, format, children }) {
  return html`
    <a class="feed-link" href=${href} target="_blank" rel="noopener">
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
  const { node, neighbours, feed } = useNetwork();

  return html`
    <section class="network" aria-labelledby="network-title">
      <header class="network-head">
        <span class="network-mark" aria-hidden="true"><${NetworkIcon} /></span>
        <div>
          <h2 id="network-title">The network</h2>
          <p>Smoke does not stop at a state line, or a national one. Each deployment is a node:
            it publishes what it detects on an open feed and reads its neighbours', so a fire
            upwind is in the forecast before the smoke arrives. What is shared is a detection
            layer, not trained weights.</p>
        </div>
      </header>

      <div class="network-grid">
        <${ThisNode} node=${node} feed=${feed} />
        <${Neighbours} neighbours=${neighbours} />
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

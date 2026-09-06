/* Jurisdiction comes from a fixed table, so the table's edges are the system's
 * edges. Publishing them is the honest move: a citizen can see in advance
 * whether their region resolves to a named authority or to a placeholder.
 *
 * The question this page answers is "what happens if I report from here", not
 * "here are some rows". So: the numbers first, the rules as sentences, and the
 * regions as cards you can scan. */

import { useMemo, useState } from "../vendor/hooks.mjs";
import { html } from "../lib/html.js";
import { useCoverage } from "../lib/store.js";
import { words } from "../lib/format.js";
import { RegionCard } from "./RegionCard.js";

const TIER_LABEL = {
  municipal: "the city's municipal corporation",
  state: "the state pollution control board",
  central: "the central board",
};

function tiles(data) {
  const stateOnly = data.regions.filter((r) => !r.municipal.length).length;
  const categories = Object.keys(data.categories).filter((k) => k !== "default").length;
  return [
    [data.region_count, "states and union territories"],
    [data.municipal_count, "municipal bodies"],
    // A zero is not worth a tile; show what is there instead of what is not.
    stateOnly
      ? [stateOnly, stateOnly === 1 ? "state with no city listed" : "states with no city listed"]
      : [categories, "kinds of report, each with its own statute"],
  ];
}

export function CoverageView() {
  const { data, error } = useCoverage();
  const [filter, setFilter] = useState("");
  const [addresses, setAddresses] = useState(false);

  const shown = useMemo(() => {
    if (!data) return [];
    const q = filter.trim().toLowerCase();
    if (!q) return data.regions;
    return data.regions.filter((r) =>
      r.region.toLowerCase().includes(q)
      || (r.state_board.name || "").toLowerCase().includes(q)
      || r.municipal.some((m) =>
        m.city.toLowerCase().includes(q) || m.name.toLowerCase().includes(q)));
  }, [data, filter]);

  const total = data ? data.regions.length : 0;

  return html`
    <div class=${addresses ? "show-addresses" : ""}>
      <header class="page-head">
        <h2>Which authorities this instance knows</h2>
        <p>Jurisdiction is resolved from a fixed table, not a live registry. A place that is
          not listed still produces a case — it just resolves to a broader authority, or to a
          placeholder, and the case says which.</p>
      </header>

      <ul class="stats">
        ${data && tiles(data).map(([n, label]) => html`
          <li key=${label}><strong>${n}</strong><span>${label}</span></li>`)}
      </ul>

      ${data && data.addresses_are_placeholders && html`
        <p class="warn">
          <strong>Every address here is a placeholder.</strong> They are on the reserved
          <code>.invalid</code> domain, which cannot receive mail, so a misconfigured run
          cannot reach a real regulator. The authority names are real and public.
        </p>`}

      <h3 class="section-label">What each kind of report is filed under</h3>
      <ul class="rules">
        ${data && Object.entries(data.categories).filter(([key]) => key !== "default")
          .map(([key, rule]) => html`
            <li key=${key}>
              <h4>${words(key)}</h4>
              <p>Goes to <strong>${TIER_LABEL[rule.tier] || rule.tier}</strong>.</p>
              <p class="rule-statute">${rule.statute}
                ${rule.section && html`<span class="muted"><br />${rule.section}</span>`}</p>
              <p class="rule-window">
                ${rule.response_window_days} days to respond before it escalates
              </p>
            </li>`)}
      </ul>

      <div class="list-head">
        <h3 class="section-label" id="coverage-list-label">
          ${shown.length === total ? "Regions" : `Regions — ${shown.length} of ${total}`}
        </h3>
        <div class="list-tools">
          <input type="search" placeholder="Find a state or city" autocomplete="off"
                 spellcheck="false" aria-describedby="coverage-list-label"
                 value=${filter} onInput=${(e) => setFilter(e.target.value)} />
          <label class="switch">
            <input type="checkbox" checked=${addresses}
                   onChange=${(e) => setAddresses(e.target.checked)} />
            <span>Show addresses</span>
          </label>
        </div>
      </div>

      ${error && html`<p class="muted empty">Could not load the table: ${error}</p>`}
      ${data && shown.length === 0 && html`
        <p class="muted empty">Nothing matches that. A place not in the table still works —
          the case resolves to the generic placeholder and says so.</p>`}

      <ul class="coverage-list">
        ${shown.map((region) => html`<${RegionCard} key=${region.region} region=${region} />`)}
      </ul>
    </div>`;
}

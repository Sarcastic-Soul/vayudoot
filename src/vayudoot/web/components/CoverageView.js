/* Jurisdiction comes from a fixed table, so the table's edges are the system's
 * edges. Publishing them is the honest move: a citizen can see in advance
 * whether their region resolves to a named authority or to a placeholder.
 *
 * The question this page answers is "what happens if I report from here", not
 * "here are some rows". So: the numbers first, the rules as sentences, and the
 * regions as cards you can scan.
 *
 * A node carries one table per country it serves — India, South Africa and
 * Brazil today — and `/authorities` publishes each under `countries`, keyed by
 * ISO code, in the same shape the top level has always had. The page opens on
 * the node's own country and switches between the rest. A report from a
 * country with no table here is refused before any model is called, and the
 * page says that too, because it is the other edge of the same coverage.
 *
 * The response window is where countries genuinely differ. India's rules set
 * statutory deadlines; South Africa's Air Quality Act and Brazil's
 * environmental agencies set none, and the table leaves `response_window_days`
 * empty with a note saying so. That is shown as what it is — no statutory
 * deadline — and never rounded into a number of days to respond. */

import { useEffect, useMemo, useState } from "../vendor/hooks.mjs";
import { html } from "../lib/html.js";
import { useCoverage } from "../lib/store.js";
import { words, countryName, plural } from "../lib/format.js";
import { RegionCard } from "./RegionCard.js";
import { CoverageSkeleton } from "./Skeletons.js";
import { Flag, FlagMark } from "./Flag.js";

/* What a region is called in each country's own administrative vocabulary.
   Wording only; the regions themselves come from the table. */
const REGION_WORD = {
  IN: ["state or union territory", "states and union territories"],
  ZA: ["province", "provinces"],
  BR: ["state", "states"],
};

const regionWord = (code, n) => {
  const [one, many] = REGION_WORD[code] || ["region", "regions"];
  return n === 1 ? one : many;
};

function tierLabel(tier, code) {
  if (tier === "municipal") return "the municipal body for the place";
  if (tier === "state") {
    return code === "IN" ? "the state pollution control board" : "the state or provincial agency";
  }
  if (tier === "central") return "the national authority";
  return tier;
}

function tiles(table, code) {
  const stateOnly = table.regions.filter((r) => !r.municipal.length).length;
  const categories = Object.keys(table.categories || {}).filter((k) => k !== "default").length;
  return [
    [table.region_count, regionWord(code, table.region_count)],
    [table.municipal_count, table.municipal_count === 1 ? "municipal body" : "municipal bodies"],
    // A zero is not worth a tile; show what is there instead of what is not.
    stateOnly
      ? [stateOnly, `${regionWord(code, stateOnly)} with no city listed`]
      : [categories, "kinds of report, each with its own statute"],
  ];
}

/* Every table the node carries, own country first. An older server without
   `countries` publishes only its own table at the top level, and that is
   shown on its own rather than as an error. */
function tablesOf(data) {
  if (!data) return [];
  const own = String(data.node_country || data.country || "IN").toUpperCase();
  const published = data.countries && Object.keys(data.countries).length
    ? data.countries : { [own]: data };
  return Object.entries(published)
    .map(([code, table]) => ({ code: code.toUpperCase(), table, own: code.toUpperCase() === own }))
    .sort((a, b) => Number(b.own) - Number(a.own) || a.code.localeCompare(b.code));
}

function CountryTabs({ tables, chosen, onChoose }) {
  if (tables.length < 2) return null;
  return html`
    <div class="country-tabs" role="tablist" aria-label="Countries this node serves">
      ${tables.map(({ code, table, own }) => html`
        <button type="button" role="tab" key=${code} id=${`country-tab-${code}`}
                aria-selected=${String(code === chosen)} aria-controls="country-panel"
                class=${`country-tab${code === chosen ? " is-chosen" : ""}`}
                onClick=${() => onChoose(code)}>
          <span class="country-flag"><${FlagMark} code=${code} size=${36} /></span>
          <span class="country-text">
            <span class="country-name">
              ${table.country_name || countryName(code)}
              ${own && html`<span class="own-tag">This node</span>`}
            </span>
            <span class="country-counts tnum">
              ${plural(table.region_count, "region")} · ${table.municipal_count} municipal
            </span>
          </span>
        </button>`)}
    </div>`;
}

/* A rule's window, said as what it is. A null window means no statute sets
   one; the case then runs on this system's follow-up interval, which the case
   view labels as not statutory. */
function RuleWindow({ rule }) {
  const days = rule.response_window_days;
  if (days === null || days === undefined) {
    return html`
      <p class="rule-window is-none">No statutory deadline</p>
      ${rule.response_window_note && html`
        <p class="rule-window-note">${rule.response_window_note}</p>`}`;
  }
  return html`<p class="rule-window">${days} days to respond · statutory</p>`;
}

export function CoverageView() {
  const { data, error } = useCoverage();
  const [filter, setFilter] = useState("");
  const [addresses, setAddresses] = useState(false);
  const tables = useMemo(() => tablesOf(data), [data]);
  const [chosen, setChosen] = useState(null);

  useEffect(() => {
    if (!chosen && tables.length) setChosen(tables[0].code);
  }, [tables]);

  const current = tables.find((t) => t.code === chosen) || tables[0] || null;
  const table = current ? current.table : null;
  const code = current ? current.code : "";

  const shown = useMemo(() => {
    if (!table) return [];
    const q = filter.trim().toLowerCase();
    if (!q) return table.regions;
    return table.regions.filter((r) =>
      r.region.toLowerCase().includes(q)
      || (r.state_board.name || "").toLowerCase().includes(q)
      || r.municipal.some((m) =>
        m.city.toLowerCase().includes(q) || m.name.toLowerCase().includes(q)));
  }, [table, filter]);

  const total = table ? table.regions.length : 0;
  const served = tables.map((t) => t.table.country_name || countryName(t.code));

  return html`
    <div class=${addresses ? "show-addresses" : ""}>
      <header class="page-head">
        <h2>Which authorities this instance knows</h2>
        <p>Jurisdiction is resolved from a fixed table per country, not a live registry. A
          place that is not listed still produces a case — it just resolves to a broader
          authority, or to a placeholder, and the case says which.</p>
      </header>

      ${!data && !error && html`<${CoverageSkeleton} />`}

      ${tables.length > 1 && html`
        <p class="served-line">
          This node serves <strong>${served.length} countries</strong>: ${served.join(", ")}.
          A report from anywhere else is not taken up — it is refused before any model is
          called, with the reason on the case.
        </p>`}

      <${CountryTabs} tables=${tables} chosen=${code} onChoose=${(c) => {
        setChosen(c); setFilter("");
      }} />

      <div id="country-panel" role=${tables.length > 1 ? "tabpanel" : null}
           aria-labelledby=${tables.length > 1 ? `country-tab-${code}` : null}>
        ${table && tables.length > 1 && html`
          <h3 class="country-title">
            <${Flag} code=${code} size=${24} />
            ${table.country_name || countryName(code)}
            ${current.own && html`<span class="own-tag">This node's own country</span>`}
          </h3>`}

        ${table && html`
          <ul class="stats">
            ${tiles(table, code).map(([n, label]) => html`
              <li key=${label}><strong class="tnum">${n}</strong><span>${label}</span></li>`)}
          </ul>`}

        ${table && table.addresses_are_placeholders !== false && html`
          <p class="warn">
            <strong>Every address here is a placeholder.</strong> They are on the reserved
            <code>.invalid</code> domain, which cannot receive mail, so a misconfigured run
            cannot reach a real regulator. The authority names are real and public.
          </p>`}

        ${table && html`
          <h3 class="section-label">What each kind of report is filed under</h3>`}
        <ul class="rules">
          ${table && Object.entries(table.categories || {}).filter(([key]) => key !== "default")
            .map(([key, rule]) => html`
              <li key=${key}>
                <h4>${words(key)}</h4>
                <p>Goes to <strong>${tierLabel(rule.tier, code)}</strong>.</p>
                <p class="rule-statute">${rule.statute}
                  ${rule.section && html`<span class="muted"><br />${rule.section}</span>`}</p>
                <${RuleWindow} rule=${rule} />
              </li>`)}
        </ul>

        <div class="list-head">
          <h3 class="section-label" id="coverage-list-label">
            ${shown.length === total
              ? `${regionWord(code, 2).replace(/^./, (c) => c.toUpperCase())}`
              : `${regionWord(code, 2).replace(/^./, (c) => c.toUpperCase())} — `
                + `${shown.length} of ${total}`}
          </h3>
          <div class="list-tools">
            <input type="search" placeholder="Find a region or city" autocomplete="off"
                   spellcheck="false" aria-describedby="coverage-list-label"
                   value=${filter} onInput=${(e) => setFilter(e.target.value)} />
            <label class="switch">
              <input type="checkbox" checked=${addresses}
                     onChange=${(e) => setAddresses(e.target.checked)} />
              <span>Show addresses</span>
            </label>
          </div>
        </div>

        ${error && html`
          <p class="note is-bad">Could not load the table: ${error}</p>`}
        ${table && shown.length === 0 && html`
          <p class="note">Nothing matches that. A place not in the table still works — the case
            resolves to the generic placeholder and says so.</p>`}

        <ul class="coverage-list">
          ${shown.map((region) => html`
            <${RegionCard} key=${`${code}:${region.region}`} region=${region} country=${code} />`)}
        </ul>
      </div>
    </div>`;
}

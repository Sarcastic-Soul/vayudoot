/* Jurisdiction comes from a fixed table, so the table's edges are the system's
 * edges. Publishing them is the honest move: a citizen can see in advance
 * whether their region resolves to a named authority or to a placeholder.
 *
 * The question this page answers is "what happens if I report from here", not
 * "here are some rows". So: the numbers first, each kind of report as one
 * routed row (type, the body it goes to, the window), and the regions as
 * collapsed rows that open onto their cities. The statute behind a rule and
 * the bodies behind a region are one click away rather than always on screen.
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
import { FlagMark } from "./Flag.js";
import {
  BuildingIcon, LandmarkIcon, GlobeIcon, ClockIcon, ShieldIcon, SearchIcon, ChevronIcon,
  FlameIcon, CropIcon, FactoryIcon, CraneIcon, CarIcon, ListIcon, ArrowIcon,
} from "./Icons.js";

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

const upper = (text) => text.replace(/^./, (c) => c.toUpperCase());

/* A glyph per kind of report, for scanning. An unknown kind gets a plain one;
   the kinds themselves come from the table. */
const KIND_ICON = {
  open_waste_burning: FlameIcon,
  crop_residue_burning: CropIcon,
  industrial_emission: FactoryIcon,
  construction_dust: CraneIcon,
  vehicle_emission: CarIcon,
};

function tierOf(tier, code) {
  if (tier === "municipal") return { label: "Municipal body", Icon: BuildingIcon };
  if (tier === "state") {
    return { label: code === "IN" ? "State board" : "State agency", Icon: LandmarkIcon };
  }
  if (tier === "central") return { label: "National authority", Icon: GlobeIcon };
  return { label: words(tier), Icon: LandmarkIcon };
}

/* The spread of statutory windows, or null when no statute sets one. */
function windowSpan(rules) {
  const days = rules.map((r) => r.response_window_days)
    .filter((d) => d !== null && d !== undefined);
  if (!days.length) return null;
  const lo = Math.min(...days);
  const hi = Math.max(...days);
  return lo === hi ? `${lo}` : `${lo}–${hi}`;
}

function tiles(table, code, rules) {
  const stateOnly = table.regions.filter((r) => !r.municipal.length).length;
  const span = windowSpan(rules);
  return [
    { n: table.region_count, label: regionWord(code, table.region_count), Icon: LandmarkIcon,
      sub: stateOnly ? `${stateOnly} with no city listed` : null },
    { n: table.municipal_count,
      label: table.municipal_count === 1 ? "municipal body" : "municipal bodies",
      Icon: BuildingIcon },
    { n: rules.length, label: rules.length === 1 ? "kind of report" : "kinds of report",
      Icon: ListIcon },
    span
      ? { n: span, label: "days to respond, by statute", Icon: ClockIcon }
      : { n: "—", label: "no statutory deadline", Icon: ClockIcon, none: true },
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
          <span class="country-flag"><${FlagMark} code=${code} size=${28} /></span>
          <span class="country-text">
            <span class="country-name">
              ${table.country_name || countryName(code)}
              ${own && html`<span class="own-tag" title="This node's own country">Home</span>`}
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
   view labels as not statutory. It is never rounded into a number of days. */
function RuleWindow({ rule }) {
  const days = rule.response_window_days;
  if (days === null || days === undefined) {
    return html`
      <span class="rule-window is-none" title=${rule.response_window_note || null}>
        No statutory deadline
      </span>`;
  }
  return html`
    <span class="rule-window" title="Set by statute">
      <${ClockIcon} /><span class="tnum">${days}</span> days
    </span>`;
}

function RouteRow({ kind, rule, code }) {
  const Kind = KIND_ICON[kind] || ListIcon;
  const tier = tierOf(rule.tier, code);
  return html`
    <li>
      <details class="route">
        <summary>
          <span class="route-kind"><span class="route-icon"><${Kind} /></span>${words(kind)}</span>
          <span class="route-arrow" aria-hidden="true"><${ArrowIcon} /></span>
          <span class=${`tier-chip is-${rule.tier}`}><${tier.Icon} />${tier.label}</span>
          <${RuleWindow} rule=${rule} />
          <span class="route-caret" aria-hidden="true"><${ChevronIcon} /></span>
        </summary>
        <div class="route-law">
          <p><strong>${rule.statute}</strong></p>
          ${rule.section && html`<p>${rule.section}</p>`}
          ${rule.response_window_note && html`<p class="muted">${rule.response_window_note}</p>`}
        </div>
      </details>
    </li>`;
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
  const rules = table
    ? Object.entries(table.categories || {}).filter(([key]) => key !== "default") : [];

  const query = filter.trim().toLowerCase();
  const shown = useMemo(() => {
    if (!table) return [];
    if (!query) return table.regions;
    return table.regions.filter((r) =>
      r.region.toLowerCase().includes(query)
      || (r.state_board.name || "").toLowerCase().includes(query)
      || r.municipal.some((m) =>
        m.city.toLowerCase().includes(query) || m.name.toLowerCase().includes(query)));
  }, [table, query]);

  const total = table ? table.regions.length : 0;
  const served = tables.map((t) => t.table.country_name || countryName(t.code));
  const body = code === "IN" ? "board" : "agency";

  return html`
    <div class=${addresses ? "show-addresses" : ""}>
      <header class="page-head">
        <h2>Authority coverage</h2>
        <p>Where each report is routed, by country, region and city.</p>
      </header>

      ${!data && !error && html`<${CoverageSkeleton} />`}

      ${tables.length > 1 && html`
        <p class="served-line"
           title=${`A report from outside ${served.join(", ")} is refused before any model `
             + "is called, with the reason on the case."}>
          <${GlobeIcon} />
          <span><strong class="tnum">${served.length}</strong> countries served</span>
          <span class="served-sep" aria-hidden="true">·</span>
          <span>elsewhere refused</span>
        </p>`}

      <${CountryTabs} tables=${tables} chosen=${code} onChoose=${(c) => {
        setChosen(c); setFilter("");
      }} />

      <div id="country-panel" role=${tables.length > 1 ? "tabpanel" : null}
           aria-labelledby=${tables.length > 1 ? `country-tab-${code}` : null}>
        ${table && html`
          <ul class="stats">
            ${tiles(table, code, rules.map(([, r]) => r)).map(({ n, label, Icon, sub, none }) => html`
              <li key=${label} class=${none ? "is-none" : ""}>
                <span class="stat-icon"><${Icon} /></span>
                <strong class="tnum">${n}</strong>
                <span class="stat-label">${label}</span>
                ${sub && html`<span class="stat-sub">${sub}</span>`}
              </li>`)}
          </ul>`}

        ${table && table.addresses_are_placeholders !== false && html`
          <p class="warn" title="The authority names are real and public.">
            <${ShieldIcon} />
            <span><strong>Placeholder addresses.</strong> Every email is on the reserved
              <code>.invalid</code> domain — nothing reaches a real regulator.</span>
          </p>`}

        ${rules.length > 0 && html`
          <h3 class="section-label">Where each report goes</h3>
          <ul class="routes">
            ${rules.map(([key, rule]) => html`
              <${RouteRow} key=${key} kind=${key} rule=${rule} code=${code} />`)}
          </ul>`}

        <div class="list-head">
          <h3 class="section-label" id="coverage-list-label">
            ${upper(regionWord(code, 2))}
            <span class="count tnum">${shown.length === total ? total : `${shown.length} / ${total}`}</span>
          </h3>
          <div class="list-tools">
            <label class="search">
              <${SearchIcon} />
              <input type="search" placeholder="Find a region or city" autocomplete="off"
                     spellcheck="false" aria-describedby="coverage-list-label"
                     value=${filter} onInput=${(e) => setFilter(e.target.value)} />
            </label>
            <label class="switch">
              <input type="checkbox" checked=${addresses}
                     onChange=${(e) => setAddresses(e.target.checked)} />
              <span>Addresses</span>
            </label>
          </div>
        </div>
        ${table && html`
          <p class="list-note">Anywhere not listed as a city routes to its region's ${body}.</p>`}

        ${error && html`
          <p class="note is-bad">Could not load the table: ${error}</p>`}
        ${table && shown.length === 0 && html`
          <p class="note">No match. An unlisted place still gets a case, routed to the
            fallback.</p>`}

        <ul class="coverage-list">
          ${shown.map((region) => html`
            <${RegionCard} key=${`${code}:${region.region}`} region=${region} country=${code}
                           open=${Boolean(query)} />`)}
        </ul>
      </div>
    </div>`;
}

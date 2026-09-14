/* The shell's one piece of chrome. Its shape is entirely a CSS question — a bar
 * under the thumb, a rail, or a labelled sidebar — so this renders the same
 * markup at every width and lets the stylesheet decide. */

import { html } from "../lib/html.js";
import { navigate } from "../lib/router.js";
import { CameraIcon, ListIcon, PinIcon, ChevronIcon, WindMark, HotspotIcon } from "./Icons.js";
import { ThemeToggle } from "./ThemeToggle.js";

/* Live first, because it is the landing surface and the unit of work. Report
 * second rather than buried: it is the intake channel the whole detection layer
 * is fed by, and it has to stay one thumb-reach away on a phone held in front
 * of the problem. */
const SECTIONS = [
  { view: "ops", target: "", label: "Live", hint: "Hotspots detected right now",
    Icon: HotspotIcon },
  { view: "report", target: "report", label: "Report", hint: "Photograph a pollution event",
    Icon: CameraIcon },
  { view: "cases", target: "cases", label: "Cases", hint: "Complaints drafted and filed",
    Icon: ListIcon },
  { view: "coverage", target: "coverage", label: "Coverage", hint: "Which authorities are known",
    Icon: PinIcon },
];

export function Sidebar({ view, collapsed, onCollapse, theme, onTheme }) {
  const label = collapsed ? "Expand the sidebar" : "Collapse the sidebar";

  return html`
    <aside class="sidebar">
      <div class="brand">
        <span class="mark" aria-hidden="true"><${WindMark} /></span>
        <div class="brand-text">
          <h1>Vayudoot</h1>
          <p>Hyper-local pollution detection</p>
        </div>
        <button type="button" class="collapse" aria-expanded=${String(!collapsed)}
                aria-label=${label} title=${label} onClick=${onCollapse}>
          <${ChevronIcon} />
        </button>
      </div>

      <nav class="nav" aria-label="Sections">
        ${SECTIONS.map(({ view: name, target, label: text, hint, Icon }) => {
          // A case and a repeat pattern are both reached from the case list,
          // so Cases stays current while either is being read.
          const active = name === view
            || (name === "ops" && view === "hotspot")
            || (name === "cases" && (view === "case" || view === "cluster"));
          return html`
            <button key=${name} class=${`nav-item${active ? " is-active" : ""}`}
                    aria-current=${active ? "page" : null}
                    onClick=${() => navigate(target)}>
              <${Icon} />
              <span class="nav-label">${text}</span>
              <span class="nav-hint">${hint}</span>
            </button>`;
        })}
      </nav>

      <div class="sidebar-foot">
        <${ThemeToggle} theme=${theme} onChoose=${onTheme} />
        <p class="sandbox-badge"
           title="Filing writes to a local outbox. No authority is contacted.">
          <span class="full">Sandbox mode</span><span class="short">Sandbox</span>
        </p>
      </div>
    </aside>`;
}

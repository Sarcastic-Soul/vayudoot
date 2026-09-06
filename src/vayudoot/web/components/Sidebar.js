/* The shell's one piece of chrome. Its shape is entirely a CSS question — a bar
 * under the thumb, a rail, or a labelled sidebar — so this renders the same
 * markup at every width and lets the stylesheet decide. */

import { html } from "../lib/html.js";
import { navigate } from "../lib/router.js";
import { CameraIcon, ListIcon, PinIcon, ChevronIcon, WindMark } from "./Icons.js";
import { ThemeToggle } from "./ThemeToggle.js";

const SECTIONS = [
  { view: "report", target: "", label: "Report", hint: "Photograph a pollution event",
    Icon: CameraIcon },
  { view: "cases", target: "cases", label: "Cases", hint: "Everything submitted so far",
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
          <p>Photograph to filed complaint</p>
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

/* The shell.
 *
 * The operations view is the landing surface: the empty hash is `ops`, not the
 * report form. That is the v0.3 reframe — the unit of work is a hotspot, a
 * place where pollution is happening, rather than one citizen's complaint — and
 * the front door has to say so. Intake keeps its own route and its own nav
 * item, unchanged and no further from a thumb than it was.
 *
 * Every view mounts only while it is the route, which is what stops the case
 * poll and the hotspot poll when the reader leaves. The report form is the one
 * exception, and only after its first visit: once it has been opened it stays
 * in the document so a half-filled form survives a look at the map. It is not
 * mounted before that, because `LocationPicker` asks for the reader's location
 * on mount, and the front door of a public dashboard is not the place to raise
 * a geolocation prompt nobody asked for. */

import { useEffect, useState } from "../vendor/hooks.mjs";
import { html, Fragment } from "../lib/html.js";
import { useRoute } from "../lib/router.js";
import { useTheme } from "../lib/theme.js";
import { useRail } from "../lib/rail.js";
import { resizeMaps } from "../lib/maps.js";
import { Sidebar } from "./Sidebar.js";
import { OpsView } from "./OpsView.js";
import { HotspotView } from "./HotspotView.js";
import { ReportForm } from "./ReportForm.js";
import { CaseView } from "./CaseView.js";
import { CasesView } from "./CasesView.js";
import { ClusterView } from "./ClusterView.js";
import { CoverageView } from "./CoverageView.js";

export function App() {
  const route = useRoute();
  const [theme, chooseTheme] = useTheme();
  const [collapsed, toggleRail] = useRail();
  const [intakeOpened, setIntakeOpened] = useState(route.view === "report");

  useEffect(() => {
    if (route.view === "report") setIntakeOpened(true);
  }, [route.view]);

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" });
    // A map that was hidden has no size; it needs telling once it is shown.
    const timer = setTimeout(resizeMaps, 80);
    return () => clearTimeout(timer);
  }, [route.view, route.caseId, route.clusterId, route.hotspotId]);

  useEffect(() => {
    let timer = null;
    const onResize = () => { clearTimeout(timer); timer = setTimeout(resizeMaps, 180); };
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); clearTimeout(timer); };
  }, []);

  const viewClass = (name) => `view${route.view === name ? " is-active" : ""}`;

  /* The skip link moves focus without touching the hash, which is the route. */
  function skip(event) {
    event.preventDefault();
    document.getElementById("main").focus();
  }

  return html`
    <${Fragment}>
      <a class="skip" href="#main" onClick=${skip}>Skip to the content</a>
      <div class="app">
        <${Sidebar} view=${route.view} collapsed=${collapsed} onCollapse=${toggleRail}
                    theme=${theme} onTheme=${chooseTheme} />
        <main id="main" tabindex="-1">
          <section class=${viewClass("ops")}>
            ${route.view === "ops" && html`<${OpsView} />`}
          </section>
          <section class=${viewClass("hotspot")}>
            ${route.view === "hotspot"
              && html`<${HotspotView} key=${route.hotspotId} hotspotId=${route.hotspotId} />`}
          </section>
          <section class=${viewClass("report")}>
            ${intakeOpened && html`<${ReportForm} />`}
          </section>
          <section class=${viewClass("case")}>
            ${route.view === "case"
              && html`<${CaseView} key=${route.caseId} caseId=${route.caseId} />`}
          </section>
          <section class=${viewClass("cases")}>
            ${route.view === "cases" && html`<${CasesView} />`}
          </section>
          <section class=${viewClass("cluster")}>
            ${route.view === "cluster"
              && html`<${ClusterView} key=${route.clusterId} clusterId=${route.clusterId} />`}
          </section>
          <section class=${viewClass("coverage")}>
            ${route.view === "coverage" && html`<${CoverageView} />`}
          </section>
        </main>
      </div>
    <//>`;
}

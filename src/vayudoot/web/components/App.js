/* The shell.
 *
 * All four sections live in the document at once and the stylesheet decides
 * which is on screen — the report form in particular, because its map and its
 * geolocation prompt belong to page load rather than to a route change. The
 * three other views mount only while they are the route, which is what stops
 * the case poll when the reader leaves. */

import { useEffect } from "../vendor/hooks.mjs";
import { html, Fragment } from "../lib/html.js";
import { useRoute } from "../lib/router.js";
import { useTheme } from "../lib/theme.js";
import { useRail } from "../lib/rail.js";
import { resizeMaps } from "../lib/maps.js";
import { Sidebar } from "./Sidebar.js";
import { ReportForm } from "./ReportForm.js";
import { CaseView } from "./CaseView.js";
import { CasesView } from "./CasesView.js";
import { CoverageView } from "./CoverageView.js";

export function App() {
  const route = useRoute();
  const [theme, chooseTheme] = useTheme();
  const [collapsed, toggleRail] = useRail();

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" });
    // A map that was hidden has no size; it needs telling once it is shown.
    const timer = setTimeout(resizeMaps, 80);
    return () => clearTimeout(timer);
  }, [route.view, route.caseId]);

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
          <section class=${viewClass("report")}><${ReportForm} /></section>
          <section class=${viewClass("case")}>
            ${route.view === "case"
              && html`<${CaseView} key=${route.caseId} caseId=${route.caseId} />`}
          </section>
          <section class=${viewClass("cases")}>
            ${route.view === "cases" && html`<${CasesView} />`}
          </section>
          <section class=${viewClass("coverage")}>
            ${route.view === "coverage" && html`<${CoverageView} />`}
          </section>
        </main>
      </div>
    <//>`;
}

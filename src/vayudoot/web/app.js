/* Entry point.
 *
 * Native ES modules, no build step: the browser loads this and follows the
 * imports. Preact and htm are vendored under `vendor/` for the same reason —
 * see the README there. */

import { render } from "./vendor/preact.mjs";
import { html } from "./lib/html.js";
import { App } from "./components/App.js";

render(html`<${App} />`, document.getElementById("root"));

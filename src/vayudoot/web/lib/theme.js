/* Three states, not two. "System" is the default and is a real choice rather
 * than the absence of one, so a reader who wants the page to follow their OS
 * can say so and have it stick. The stored value is all that persists;
 * everything visual comes from the data-theme attribute the CSS reads. */

import { useState } from "../vendor/hooks.mjs";

const KEY = "vayudoot.theme";

function stored() {
  try { return localStorage.getItem(KEY) || "system"; } catch { return "system"; }
}

export function applyTheme(choice) {
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
  try { localStorage.setItem(KEY, choice); } catch { /* private mode */ }
}

/* Applied at import time, before the first render, so the page never flashes
 * the wrong theme. */
applyTheme(stored());

export function useTheme() {
  const [theme, setTheme] = useState(stored);
  return [theme, (choice) => { applyTheme(choice); setTheme(choice); }];
}

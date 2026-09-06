/* One binding of htm to Preact's createElement, imported everywhere else.
 *
 * There is no build step: the browser loads these modules directly, so the
 * template literal is the JSX. Keeping the binding in one place means a
 * component file only ever imports `html`. */

import { h } from "../vendor/preact.mjs";
import htm from "../vendor/htm.mjs";

export const html = htm.bind(h);
export { Fragment } from "../vendor/preact.mjs";

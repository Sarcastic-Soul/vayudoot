/* Loading states.
 *
 * A skeleton rather than a spinner, because the shape of what is coming is
 * itself information: a case has a photograph and four stages, a list has
 * cards. It also stops the page jumping when the data lands, which on a phone
 * held at arm's length is the difference between "loading" and "broken".
 *
 * Each block is marked `aria-hidden` and paired with a live text announcement,
 * so a screen reader hears "Loading the case" once instead of reading a dozen
 * empty boxes. */

import { html, Fragment } from "../lib/html.js";

const Bars = ({ count }) => html`
  <${Fragment}>
    ${Array.from({ length: count }, (_, i) => html`<span key=${i} class="skeleton"></span>`)}
  <//>`;

export function CaseStatusSkeleton() {
  return html`
    <${Fragment}>
      <p class="visually-hidden" role="status">Loading the case.</p>
      <div aria-hidden="true">
        <div class="skeleton case-photo-skeleton"></div>
        <ol class="timeline">
          ${[0, 1, 2, 3].map((i) => html`
            <li key=${i} class="step" data-state="pending">
              <span class="step-node"></span>
              <div class="step-body step-skeleton"><${Bars} count=${3} /></div>
            </li>`)}
        </ol>
      </div>
    <//>`;
}

export function CaseListSkeleton() {
  return html`
    <${Fragment}>
      <p class="visually-hidden" role="status">Loading your cases.</p>
      <ul class="case-list-skeleton" aria-hidden="true">
        ${[0, 1, 2].map((i) => html`<li key=${i} class="skeleton"></li>`)}
      </ul>
    <//>`;
}

export function CoverageSkeleton() {
  return html`
    <${Fragment}>
      <p class="visually-hidden" role="status">Loading the authority table.</p>
      <div aria-hidden="true">
        <ul class="stats">
          ${[0, 1, 2].map((i) => html`<li key=${i} class="skeleton stat-skeleton"></li>`)}
        </ul>
        <ul class="coverage-list">
          ${[0, 1, 2, 3].map((i) => html`<li key=${i} class="skeleton region-skeleton"></li>`)}
        </ul>
      </div>
    <//>`;
}

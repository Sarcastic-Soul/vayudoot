/* Where the API lives, relative to wherever this page was served from.
 *
 * FastAPI serves this interface itself, so by default every request goes to
 * the page's own origin and the base is empty. The public deployment splits
 * the two: the static files sit on Firebase Hosting and the API runs on
 * Render. Firebase's free plan cannot proxy to an outside host, so a page
 * served from a Firebase domain has to call the API across origins instead.
 *
 * A classic script rather than a module, loaded before `app.js`, so the value
 * is set before any module asks for it. A deployment whose API runs somewhere
 * else changes the one URL below and nothing more. */

(function () {
  var host = location.hostname;
  var onFirebase = /\.web\.app$/.test(host) || /\.firebaseapp\.com$/.test(host);
  window.VAYUDOOT_API_BASE = onFirebase ? "https://vayudoot.onrender.com" : "";
})();

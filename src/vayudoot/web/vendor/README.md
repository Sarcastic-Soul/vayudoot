# Vendored runtime

Preact 10.24.3, its hooks, and htm 3.1.1, copied here rather than loaded from a
CDN. Three reasons:

- The app runs on a free container with no build step, so there is no bundler to
  resolve `import "preact"`. Native ES modules need a real path.
- A CDN is a third party in the request path of a page a citizen uses to file a
  complaint. Leaflet is already one; a second was avoidable.
- Pinned bytes cannot change underneath us.

`hooks.mjs` had its `from"preact"` specifier rewritten to `./preact.mjs`. That is
the only edit made to any of them. To upgrade: re-download from unpkg at the new
version and redo that one rewrite.

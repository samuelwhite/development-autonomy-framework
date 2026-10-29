'use strict';

// Exact asset allowlist: no arbitrary files, HTTP server or renderer/native bridge.
const assets = Object.freeze({
  '/index.html': 'text/html; charset=utf-8',
  '/style.css': 'text/css; charset=utf-8',
  '/simulation.js': 'text/javascript; charset=utf-8',
  '/app.js': 'text/javascript; charset=utf-8',
});
const home = 'daf://app/index.html';
function assetFor(raw) {
  try {
    const url = new URL(raw);
    if (url.protocol !== 'daf:' || url.host !== 'app' || url.username || url.password || url.search) return null;
    // Reject encoded paths and traversal even when URL parsing normalises them.
    if (raw.split('#')[0] !== `daf://app${url.pathname}`) return null;
    return Object.hasOwn(assets, url.pathname) ? url.pathname : null;
  } catch { return null; }
}
function canNavigate(raw) { return assetFor(raw) === '/index.html'; }
const csp = "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'; frame-ancestors 'none'; worker-src 'none'";
module.exports = { assets, assetFor, canNavigate, home, csp };

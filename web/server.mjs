import { createHash, timingSafeEqual } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { pathToFileURL } from 'node:url';
import { assertViewerAuthentication, loadConfig } from './config.mjs';
import { createFeed } from './feed.mjs';

const assets = new Map([
  ['/', ['text/html; charset=utf-8', 'index.html']],
  ['/style.css', ['text/css; charset=utf-8', 'style.css']],
  ['/app.js', ['text/javascript; charset=utf-8', 'app.js']],
].map(([route, [type, file]]) => [route, [type, readFileSync(new URL(`./public/${file}`, import.meta.url))]]));
const headers = {
  'Cache-Control': 'no-store',
  'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; " +
    "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'X-Frame-Options': 'DENY',
  'Cross-Origin-Resource-Policy': 'same-origin',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
};
const digest = (value) => createHash('sha256').update(value).digest();

export function missionControl(config, options = {}) {
  assertViewerAuthentication(config);
  const abort = new AbortController();
  const feed = createFeed({ ...options, ...config, signal: abort.signal });
  const expected = config.password && digest(`daf:${config.password}`);
  const http = createServer({ maxHeaderSize: 8_192, requestTimeout: 15_000, headersTimeout: 10_000 },
    async (request, response) => {
      const send = (status, type, body, extra = {}) => {
        response.writeHead(status, { ...headers, ...extra, 'Content-Type': type });
        response.end(request.method === 'HEAD' ? undefined : body);
      };
      const plain = 'text/plain; charset=utf-8';
      if (request.method !== 'GET' && request.method !== 'HEAD') {
        return send(405, plain, 'Read-only endpoint', { Allow: 'GET, HEAD' });
      }
      if (request.url === '/healthz') return send(200, plain, 'ok');
      if (expected) {
        const authorization = request.headers.authorization || '';
        const credentials = /^Basic ([A-Za-z0-9+/]+={0,2})$/i.exec(authorization);
        if (!credentials || !timingSafeEqual(expected, digest(Buffer.from(credentials[1], 'base64')))) {
          return send(401, plain, 'Viewer authentication required', {
            'WWW-Authenticate': 'Basic realm="DAF Mission Control", charset="UTF-8"',
          });
        }
      }
      if (request.url === '/api/mission-control') {
        try {
          const json = request.method === 'HEAD' ? '' : JSON.stringify(await feed());
          return send(200, 'application/json; charset=utf-8', json);
        } catch {
          return send(503, plain, 'Mission Control data unavailable');
        }
      }
      const asset = assets.get(request.url);
      return asset ? send(200, ...asset) : send(404, plain, 'Page not found');
    });
  http.maxConnections = 64;
  return {
    http,
    stop() {
      abort.abort();
      return new Promise((resolve) => {
        const deadline = setTimeout(() => http.closeAllConnections(), 3_000);
        deadline.unref();
        http.close(() => { clearTimeout(deadline); resolve(); });
      });
    },
  };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    const config = loadConfig();
    const { http, stop } = missionControl(config);
    http.on('error', () => {
      console.error('Mission Control could not bind its configured listener');
      process.exitCode = 1;
    });
    http.listen(config.port, config.host, () => {
      console.log(`Mission Control listening on http://${config.host}:${config.port}`);
    });
    process.once('SIGTERM', stop);
    process.once('SIGINT', stop);
  } catch {
    console.error('Mission Control configuration could not be loaded');
    process.exitCode = 1;
  }
}

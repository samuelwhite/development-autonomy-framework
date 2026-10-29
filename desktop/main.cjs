'use strict';

const { app, BrowserWindow, Menu, dialog, protocol, session } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const { assets, assetFor, canNavigate, home, csp } = require('./policy.cjs');

app.setName('DAF Offline Demo');
app.setAppUserModelId('org.daf.offline-demo');
app.enableSandbox();
// Chromium background facilities must not contact services in this offline demo.
for (const flag of ['disable-background-networking', 'disable-component-update',
  'disable-domain-reliability', 'disable-sync', 'no-pings']) app.commandLine.appendSwitch(flag);
app.commandLine.appendSwitch('host-resolver-rules', 'MAP * ~NOTFOUND');
app.commandLine.appendSwitch('force-webrtc-ip-handling-policy', 'disable_non_proxied_udp');
protocol.registerSchemesAsPrivileged([{ scheme: 'daf', privileges: { standard: true, secure: true } }]);

let win;
let reportingFailure = false;
function fail(message) {
  if (reportingFailure) return;
  reportingFailure = true;
  dialog.showErrorBox('DAF could not open the offline demo', `${message}\n\nClose DAF, extract the whole ZIP into a new folder and open DAF again. Keep all the files together. If Windows blocks it, stop and ask the distributor for an approved signed build; do not disable security protections. No real task was running.`);
  app.quit();
}

async function start() {
  const assetRoot = path.join(__dirname, app.isPackaged ? 'ui' : '../prototype');
  // Check the complete UI up front so missing files cannot leave a blank window.
  const files = new Map(Object.keys(assets).map(name => [name, fs.readFileSync(path.join(assetRoot, name.slice(1)))]));
  const offline = session.fromPartition('daf-offline', { cache: false });
  // Defence in depth: reject network at the session layer, even if UI CSP changes.
  offline.webRequest.onBeforeRequest((details, done) => done({ cancel: !assetFor(details.url) }));
  offline.setPermissionRequestHandler((_contents, _permission, done) => done(false));
  offline.setPermissionCheckHandler(() => false);
  offline.on('will-download', event => event.preventDefault());
  offline.protocol.handle('daf', request => {
    const asset = assetFor(request.url);
    if (request.method !== 'GET' || !asset) return new Response('Unavailable in this offline demo', { status: 403 });
    return new Response(files.get(asset), { headers: {
      'Content-Type': assets[asset], 'Content-Security-Policy': csp,
      'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store',
    } });
  });
  win = new BrowserWindow({
    width: 1320, height: 940, minWidth: 680, minHeight: 520,
    title: 'DAF 0.2.1 · Offline demo', backgroundColor: '#f6f7fb', show: false,
    webPreferences: {
      session: offline, sandbox: true, contextIsolation: true, nodeIntegration: false,
      webSecurity: true, webviewTag: false, spellcheck: false,
      // No preload and no IPC capability are exposed to the prototype.
    },
  });
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', (event, url) => { if (!canNavigate(url)) event.preventDefault(); });
  win.webContents.on('will-redirect', event => event.preventDefault());
  win.webContents.on('will-attach-webview', event => event.preventDefault());
  win.webContents.on('page-title-updated', event => event.preventDefault());
  win.webContents.on('render-process-gone', () => fail('The demo window stopped responding. Reopening starts a fresh demonstration.'));
  win.webContents.on('did-fail-load', (_event, code, _description, _url, mainFrame) => {
    if (mainFrame && code !== -3) fail('DAF could not read its bundled screens.');
  });
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: 'Demo', submenu: [
      { label: 'Reload / demonstrate interruption', accelerator: 'CmdOrCtrl+R', click: () => win.webContents.reload() },
      { type: 'separator' }, { role: 'quit', label: 'Exit DAF' },
    ] },
    { label: 'View', submenu: [{ role: 'zoomIn' }, { role: 'zoomOut' }, { role: 'resetZoom' }] },
    { label: 'Help', submenu: [{ label: 'About this offline demo', click: () => dialog.showMessageBox(win, {
      type: 'info', title: 'DAF 0.2.1 · Offline demo', message: 'Everything in this application is simulated.',
      detail: 'No AI connections, credentials, paid requests, project access, telemetry or automatic updates. Closing ends the demo and clears progress. Reload demonstrates interruption within this session. See START-HERE.txt beside DAF for installation and removal instructions.',
    }) }] },
  ]));
  await win.loadURL(home);
  win.show();
}

app.on('window-all-closed', () => app.quit());
app.whenReady().then(start).catch(() => fail('Some application files are missing or cannot be read.'));

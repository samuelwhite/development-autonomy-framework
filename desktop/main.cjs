'use strict';

const { app, BrowserWindow, Menu, dialog, protocol, session, ipcMain } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const { assets, assetFor, canNavigate, home, csp } = require('./policy.cjs');
const {PlanningProcess} = require('./planning-process.cjs');
const {installPlanningIPC} = require('./planning-ipc.cjs');

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
let cancelPlanning = async () => {};
let exiting = false;
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
  const files = new Map(Object.keys(assets).map(name => [name, fs.readFileSync(path.join(
    !app.isPackaged && name.startsWith('/planning.') ? __dirname : assetRoot, name.slice(1)))]));
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
    title: 'DAF · Demo and read-only planning', backgroundColor: '#f6f7fb', show: false,
    webPreferences: {
      session: offline, sandbox: true, contextIsolation: true, nodeIntegration: false,
      webSecurity: true, webviewTag: false, spellcheck: false,
      preload: path.join(__dirname, 'preload.cjs'),
    },
  });
  const resources = app.isPackaged ? path.join(process.resourcesPath, 'planning') : path.join(__dirname, '../dist/m1.2-runtime', process.platform);
  const runner = new PlanningProcess(resources, path.join(app.getPath('userData'), 'planning-v1'));
  cancelPlanning = installPlanningIPC({ipcMain, dialog, win, runner});
  win.webContents.on('did-start-navigation', (_event, _url, _inPlace, mainFrame) => { if(mainFrame) void cancelPlanning(); });
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
      type: 'info', title: 'DAF · M1.2 review candidate', message: 'Offline demonstration and real read-only GitHub planning.',
      detail: 'The demo remains simulated. Import from GitHub reads only a public, commit-pinned plan after your confirmation. Imported work stays proposed: no execution, AI providers, credentials or spending. Local snapshots survive closing; demo progress does not. See START-HERE.txt for installation, storage and removal.',
    }) }] },
  ]));
  await win.loadURL(home);
  win.show();
}

app.on('window-all-closed', () => app.quit());
app.on('before-quit', event => {
  if(exiting) return;
  event.preventDefault(); exiting = true;
  void cancelPlanning().finally(() => app.quit());
});
if (!app.requestSingleInstanceLock()) app.quit();
else app.whenReady().then(start).catch(() => fail('Some application files are missing or cannot be read.'));

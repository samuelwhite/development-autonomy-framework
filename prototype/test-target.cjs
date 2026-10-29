'use strict';
const path = require('node:path');
const fs = require('node:fs/promises');
const { pathToFileURL } = require('node:url');
const playwright = require(process.env.DAF_PLAYWRIGHT_PATH || 'playwright');
const desktop = process.env.DAF_DESKTOP_EXECUTABLE;
const url = desktop ? 'daf://app/index.html' : pathToFileURL(path.join(__dirname, 'index.html')).href;
const isLocal = raw => desktop ? raw.startsWith('daf://app/') : raw.startsWith('file:');

// Run the same approved UI assertions in Chromium or the actual packaged window.
async function launchTarget() {
  if (!desktop) return playwright.chromium.launch({ headless: true });
  const apps = [];
  let sequence = 0;
  return {
    async newContext(options) {
      const env = { ...process.env };
      delete env.ELECTRON_RUN_AS_NODE;
      delete env.NODE_OPTIONS;
      if (process.platform === 'win32') env.PATH = `${env.SystemRoot}\\System32;${env.SystemRoot}`;
      const output = path.resolve(__dirname, '../desktop/test-output');
      await fs.mkdir(output, { recursive: true });
      const logPath = path.join(output, `journey-${process.pid}-${++sequence}.json`);
      const app = await playwright._electron.launch({ executablePath: desktop, env, chromiumSandbox: true, timeout: 30000, args: [`--log-net-log=${logPath}`] });
      apps.push(app);
      const page = await app.firstWindow();
      await page.waitForURL(url);
      await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.session.enableNetworkEmulation({ offline: true }));
      // fresh() in the UI suite means a fresh tab; here it means a fresh demo
      // inside the same native window. Closing the application is tested separately.
      page.close = async () => {};
      return {
        async newPage() {
          page.removeAllListeners('request'); page.removeAllListeners('pageerror');
          await page.evaluate(() => sessionStorage.clear());
          await page.setViewportSize(options.viewport || { width: 1440, height: 1000 });
          return page;
        },
        addInitScript: script => app.context().addInitScript(script),
        async close() {
          await app.close(); apps.splice(apps.indexOf(app), 1);
          const log = JSON.parse(await fs.readFile(logPath, 'utf8'));
          const { auditNetwork } = require('../desktop/tests/network-audit.cjs');
          await fs.writeFile(`${logPath.slice(0, -5)}-summary.json`, JSON.stringify({ ...auditNetwork(log), rendererOffline: true }));
        },
      };
    },
    async close() { for (const app of apps) await app.close(); },
  };
}
module.exports = { launchTarget, url, isLocal };

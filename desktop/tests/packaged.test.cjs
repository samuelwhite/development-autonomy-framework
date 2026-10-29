'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const http = require('node:http');
const { pathToFileURL } = require('node:url');
const { _electron } = require('playwright');
const executablePath = process.env.DAF_DESKTOP_EXECUTABLE;

async function launch(args = []) {
  const env = { ...process.env };
  delete env.ELECTRON_RUN_AS_NODE; delete env.NODE_OPTIONS;
  if (process.platform === 'win32') env.PATH = `${env.SystemRoot}\\System32;${env.SystemRoot}`;
  const app = await _electron.launch({ executablePath, args, env, chromiumSandbox: true });
  const page = await app.firstWindow();
  await page.getByRole('heading', { name: 'Your next idea. Within reach.' }).waitFor();
  return { app, page };
}

test('packaged security boundary, native close/relaunch and Chromium network log', { timeout: 60000 }, async () => {
  const output = path.resolve(__dirname, '../test-output');
  await fs.mkdir(output, { recursive: true });
  const netlog = path.join(output, 'network.json');
  const sentinel = path.join(output, 'must-not-read.txt');
  await fs.writeFile(sentinel, 'This local test file must not be served to the application.');
  const { app, page } = await launch([`--log-net-log=${netlog}`]);
  let closedNormally = false;
  let requests = 0;
  const server = http.createServer((_request, response) => { requests++; response.end('unexpected'); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    assert.equal(await page.evaluate(() => typeof require), 'undefined');
    assert.equal(await page.evaluate(() => typeof process), 'undefined');
    assert.equal(await page.evaluate(() => typeof window.electron), 'undefined');
    const preferences = await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.getLastWebPreferences());
    assert.equal(preferences.sandbox, true); assert.equal(preferences.contextIsolation, true);
    assert.equal(preferences.nodeIntegration, false); assert.equal(preferences.webviewTag, false);
    assert.equal(await page.evaluate(() => window.open('https://example.invalid')), null);
    assert.equal(app.windows().length, 1);
    const blocked = await app.evaluate(async ({ BrowserWindow }, { port, localFile }) => {
      const session = BrowserWindow.getAllWindows()[0].webContents.session;
      const urls = [`http://127.0.0.1:${port}/`, 'https://example.invalid/', localFile, 'daf://app/main.cjs'];
      return Promise.all(urls.map(async url => {
        try { const response = await session.fetch(url); return !response.ok; } catch { return true; }
      }));
    }, { port: server.address().port, localFile: pathToFileURL(sentinel).href });
    assert.deepEqual(blocked, [true, true, true, true]);
    assert.equal(requests, 0);
    await page.getByRole('button', { name: 'Let’s get started →' }).click();
    await page.evaluate(() => { location.href = 'https://example.invalid/'; });
    await page.waitForTimeout(250);
    assert.equal(page.url(), 'daf://app/index.html');
    // A normal window close exits the whole application, with no background task.
    const closed = app.waitForEvent('close');
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close());
    await closed;
    closedNormally = true;
  } finally {
    server.close();
    if (!closedNormally) await app.close();
  }
  const log = JSON.parse(await fs.readFile(netlog, 'utf8'));
  const eventNames = new Map(Object.entries(log.constants.logEventTypes).map(([name, id]) => [id, name]));
  // Includes Chromium background traffic, not just page requests. Playwright's
  // local debug pipe/inspector exists only during this test, not ordinary launch.
  const connections = log.events.filter(event => ['TCP_CONNECT', 'UDP_CONNECT', 'SOCKET_ALIVE'].includes(eventNames.get(event.type)));
  assert.deepEqual(connections, [], 'No outbound socket may be opened, even for deliberate blocked probes');
  await fs.writeFile(path.join(output, 'boundary-summary.json'), JSON.stringify({
    outboundSocketEvents: connections.length, blockedProbeCount: 4, localServerRequests: requests,
    rendererSandbox: true, rendererNodeAccess: false, nativeClose: 'passed',
  }, null, 2));
  const next = await launch();
  try { assert.equal(await next.page.locator('[name="provider"]').count(), 0); }
  finally { await next.app.close(); }
});

test('renderer failure gives actionable recovery without resuming work', { timeout: 30000 }, async () => {
  const { app } = await launch();
  try {
    await app.evaluate(({ app, dialog, BrowserWindow }) => {
      global.savedQuit = app.quit;
      dialog.showErrorBox = (title, message) => { global.failure = { title, message }; };
      app.quit = () => { global.quitRequested = true; };
      BrowserWindow.getAllWindows()[0].webContents.forcefullyCrashRenderer();
    });
    let result;
    for (let i = 0; i < 50; i++) {
      result = await app.evaluate(() => ({ failure: global.failure, quitRequested: global.quitRequested }));
      if (result.failure) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.match(result.failure.message, /Reopening starts a fresh demonstration/);
    assert.match(result.failure.message, /extract the whole ZIP/);
    assert.equal(result.quitRequested, true);
  } finally {
    await app.evaluate(({ app }) => { app.quit = global.savedQuit; });
    await app.close();
  }
});

test('keyboard-only onboarding reaches Mission Control and finishes a task', { timeout: 30000 }, async () => {
  const { app, page } = await launch();
  async function activate(selector) {
    for (let i = 0; i < 40; i++) {
      if (await page.evaluate(selector => document.activeElement.matches(selector), selector)) {
        await page.keyboard.press('Enter'); return;
      }
      await page.keyboard.press('Tab');
    }
    assert.fail(`Keyboard could not reach ${selector}`);
  }
  try {
    await activate('.skip');
    await activate('[data-action="next"]');
    for (let i = 0; i < 20; i++) {
      if (await page.evaluate(() => document.activeElement.matches('[name="provider"]'))) break;
      await page.keyboard.press('Tab');
    }
    await page.keyboard.press('Space');
    assert.equal(await page.locator('[name="provider"]:checked').count(), 1);
    await activate('[data-action="next"]'); await activate('[data-action="connect"]');
    await activate('[data-action="next"]'); await activate('[data-action="next"]');
    await page.getByRole('heading', { name: 'Start with a useful little task' }).waitFor();
    await activate('[data-action="begin"]');
    await page.locator('.status-badge').filter({ hasText: 'Task complete' }).waitFor();
    assert.match(await page.locator('main').textContent(), /Mission Control/);
    // Native zoom preserves a reachable Stop control and readable layout.
    await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.setZoomFactor(2));
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.equal(await page.getByRole('button', { name: '■ Stop task', exact: true }).isVisible(), true);
  } finally { await app.close(); }
});

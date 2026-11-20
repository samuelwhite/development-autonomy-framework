import assert from 'node:assert/strict';
import { mkdir, mkdtemp, rm } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { bootstrapAccounts } from '../accounts.mjs';
import { missionControl } from '../server.mjs';

const { chromium } = createRequire(new URL('../../desktop/package.json', import.meta.url))('playwright');
const output = process.env.DAF_ACCOUNTS_SCREENSHOTS;
const channel = process.env.DAF_WEB_BROWSER_CHANNEL;
const adminPassword = 'copper lanterns light the old signal tower';
const viewerPassword = 'several rivers cross the valley before dawn';
const changedPassword = 'river stones keep the memory of rain';
const resetPassword = 'orchard paths circle back through sunlight';

test('administrator and viewer use local accounts in the browser', { timeout: 45_000 }, async (t) => {
  const directory = await mkdtemp(join(tmpdir(), 'daf-account-browser-'));
  let app;
  let browser;
  t.after(async () => {
    try { await browser?.close(); } finally {
      try { await app?.stop(); } finally { await rm(directory, { recursive: true, force: true }); }
    }
  });
  await bootstrapAccounts(directory, 'demo.admin', adminPassword);
  const reserved = createServer();
  await new Promise((resolve) => reserved.listen(0, '127.0.0.1', resolve));
  const { port } = reserved.address();
  await new Promise((resolve) => reserved.close(resolve));
  const origin = `http://127.0.0.1:${port}`;
  app = missionControl({ repositories: [], host: '127.0.0.1', authMode: 'accounts',
    authDirectory: directory, publicOrigin: origin });
  await new Promise((resolve, reject) => {
    app.http.once('error', reject);
    app.http.listen(port, '127.0.0.1', resolve);
  });
  browser = await chromium.launch(channel ? { channel } : {});
  const desktop = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const phone = await browser.newPage({ viewport: { width: 390, height: 844 }, reducedMotion: 'reduce' });
  desktop.setDefaultTimeout(6_000);
  phone.setDefaultTimeout(6_000);
  const noOverflow = (page) => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);
  const capture = async (page, subject) => {
    for (const theme of ['light', 'dark']) {
      const appearance = page.getByLabel('Appearance');
      await appearance.selectOption(theme);
      await appearance.blur();
      assert.ok(await noOverflow(page));
      assert.equal(await page.locator('html').getAttribute('data-theme'), theme);
      if (output) {
        await mkdir(output, { recursive: true });
        await page.screenshot({ path: join(output, `ui03-${subject}-${theme}.png`), fullPage: true });
      }
    }
  };
  const signIn = async (page, name, password) => {
    await page.getByRole('textbox', { name: 'Username' }).fill(name);
    await page.getByLabel('Password', { exact: true }).fill(password);
    await page.getByRole('button', { name: 'Sign in' }).click();
    await page.getByRole('link', { name: 'My account' }).waitFor();
  };

  await desktop.goto(origin);
  await desktop.getByRole('heading', { name: 'Sign in to Mission Control' }).waitFor();
  await desktop.keyboard.press('Tab');
  assert.equal(await desktop.locator(':focus').getAttribute('href'), '/');
  await phone.goto(origin);
  await capture(phone, 'phone-sign-in');
  await phone.getByRole('checkbox', { name: 'Show password' }).check();
  assert.equal(await phone.getByLabel('Password', { exact: true }).getAttribute('type'), 'text');
  await phone.getByRole('checkbox', { name: 'Show password' }).uncheck();
  await signIn(desktop, 'demo.admin', adminPassword);
  const session = (await desktop.context().cookies()).find((item) => item.name === '__Host-daf_session');
  assert.ok(session?.httpOnly && session.secure && session.sameSite === 'Strict');
  await desktop.getByRole('link', { name: 'Settings / Users' }).click();
  await desktop.getByRole('heading', { name: 'Users', exact: true }).waitFor();
  assert.ok(await desktop.getByRole('button', { name: 'Disable demo.admin' }).isDisabled());
  const add = desktop.locator('#create-user');
  await add.getByLabel('Username').fill('demo.viewer');
  await add.getByLabel('Password', { exact: true }).fill(viewerPassword);
  await add.getByRole('button', { name: 'Add user' }).click();
  await desktop.getByRole('heading', { name: 'demo.viewer' }).waitFor();
  await capture(desktop, 'desktop-users');

  await signIn(phone, 'demo.viewer', viewerPassword);
  assert.equal(await phone.getByRole('link', { name: 'Settings / Users' }).count(), 0);
  assert.equal((await phone.request.get(origin + '/settings/users')).status(), 403);
  await phone.getByRole('link', { name: 'My account' }).click();
  await phone.getByRole('heading', { name: 'Change password' }).waitFor();
  await phone.getByLabel('Current password').fill(viewerPassword);
  await phone.getByLabel('New password').fill(changedPassword);
  await phone.getByRole('button', { name: 'Change password' }).click();
  await phone.getByRole('heading', { name: 'Sign in to Mission Control' }).waitFor();
  await signIn(phone, 'demo.viewer', changedPassword);
  await desktop.getByLabel('Reset password for demo.viewer').click();
  const reset = desktop.locator('details[open] form');
  await reset.getByLabel('New password').fill(resetPassword);
  await reset.getByRole('button', { name: 'Set password' }).click();
  await desktop.getByText('Password reset for demo.viewer.', { exact: true }).waitFor();
  assert.equal((await phone.request.get(origin + '/api/mission-control')).status(), 401);
  await desktop.getByRole('button', { name: 'Disable demo.viewer' }).click();
  await desktop.getByRole('button', { name: 'Enable demo.viewer' }).waitFor();
  await desktop.getByRole('button', { name: 'Sign out' }).click();
  await desktop.getByRole('heading', { name: 'Sign in to Mission Control' }).waitFor();
  assert.equal((await desktop.request.get(origin + '/api/mission-control')).status(), 401);
});

import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';
import { missionControl } from '../server.mjs';
import { entry, githubFixture, listen, title } from './fixtures.mjs';

const { chromium } = createRequire(new URL('../../desktop/package.json', import.meta.url))('playwright');
const channel = process.env.DAF_WEB_BROWSER_CHANNEL;
const live = process.env.DAF_WEB_LIVE_URL;
const output = process.env.DAF_WEB_SCREENSHOTS;
const launch = () => chromium.launch(channel ? { channel } : {});

async function noHorizontalOverflow(page) {
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
}

test('responsive dashboard navigates source-linked planning and job evidence safely', { timeout: 30_000 }, async (t) => {
  const app = missionControl({ repositories: [entry] }, { fetcher: githubFixture });
  let browser;
  t.after(async () => { try { await browser?.close(); } finally { await app.stop(); } });
  const origin = await listen(app);
  browser = await launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(5_000);
  const errors = [];
  const outside = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('dialog', (dialog) => { errors.push(dialog.message()); void dialog.dismiss(); });
  page.on('request', (request) => { if (!request.url().startsWith(`${origin}/`)) outside.push(request.url()); });
  await page.goto(origin);
  await page.getByText('GitHub sources checked', { exact: false }).waitFor();
  await page.keyboard.press('Tab');
  assert.equal(await page.locator(':focus').textContent(), 'Skip to content');
  await page.keyboard.press('Enter');
  assert.equal(await page.locator(':focus').getAttribute('id'), 'content');
  await page.getByRole('heading', { name: 'Needs attention' }).waitFor();
  await page.getByText('Failed · failure').first().waitFor();
  const attack = page.getByRole('link', { name: `#4 ${title}`, exact: true });
  assert.equal(await attack.getAttribute('href'), 'https://github.com/example/project/issues/4');
  assert.equal(await page.locator('img, [onerror], iframe, form').count(), 0);

  const nav = page.getByRole('navigation', { name: 'Workspace' });
  await nav.getByRole('link', { name: 'Development' }).focus();
  await page.keyboard.press('Enter');
  await page.getByRole('heading', { level: 1, name: 'Development' }).waitFor();
  assert.equal(await page.locator(':focus').getAttribute('id'), 'heading');
  assert.equal(await nav.getByRole('link', { name: 'Development' }).getAttribute('aria-current'), 'page');
  assert.match(await page.getByRole('link', { name: 'Plan source' }).getAttribute('href'), /\/blob\/a{40}\/docs\/plan\.json$/);
  await page.getByText('Proposed', { exact: true }).waitFor();
  await page.getByText('Draft', { exact: true }).waitFor();
  await page.getByRole('heading', { name: 'Validation evidence' }).waitFor();
  assert.match(await page.getByRole('link', { name: 'Artifacts' }).getAttribute('href'), /\/attempts\/2#artifacts$/);

  await nav.getByRole('link', { name: 'HomeCI' }).click();
  await page.getByText('Live runner health is not connected.', { exact: false }).waitFor();
  await page.getByRole('link', { name: 'observed-runner', exact: true }).waitFor();
  const jobSummary = page.getByText('1 of 1 jobs shown');
  await jobSummary.click();
  assert.equal(await page.getByRole('link', { name: 'Job log' }).getAttribute('href'),
    'https://github.com/example/project/actions/runs/123/job/456');
  for (const width of [1440, 760, 390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await noHorizontalOverflow(page);
  }
  await page.getByRole('button', { name: 'Refresh view' }).click();
  await page.getByText('GitHub sources checked', { exact: false }).waitFor();
  await page.getByRole('link', { name: 'Job log' }).waitFor();
  assert.deepEqual(await page.getByRole('button').allTextContents(), ['Refresh view']);
  assert.deepEqual(errors, []);
  assert.deepEqual(outside, []);
});

test('browser shows initial connection failure, stale data after disconnect, and clears it on 401', { timeout: 30_000 }, async (t) => {
  const app = missionControl({ repositories: [entry] }, { fetcher: githubFixture });
  let browser;
  t.after(async () => { try { await browser?.close(); } finally { await app.stop(); } });
  const origin = await listen(app);
  browser = await launch();
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  page.setDefaultTimeout(5_000);
  let status = 0;
  await page.route('**/api/mission-control', async (route) => {
    if (status === 0) await route.abort('connectionfailed');
    else if (status === 401) await route.fulfill({ status });
    else await route.continue();
  });
  await page.goto(origin);
  await page.getByRole('status').filter({ hasText: 'Cannot connect to Mission Control' }).waitFor();
  status = 200;
  await page.getByRole('button', { name: 'Refresh view' }).click();
  await page.getByRole('status').filter({ hasText: 'GitHub sources checked' }).waitFor();
  status = 0;
  await page.getByRole('button', { name: 'Refresh view' }).click();
  await page.getByRole('status').filter({ hasText: 'Connection to Mission Control lost' }).waitFor();
  await page.getByText('Stale result', { exact: false }).first().waitFor();
  status = 401;
  await page.getByRole('button', { name: 'Refresh view' }).click();
  await page.getByRole('status').filter({ hasText: 'Viewer access is required' }).waitFor();
  assert.equal(await page.getByRole('heading', { name: 'Latest validation' }).count(), 0);
});

test('capture real public DAF planning and Actions in desktop and phone views',
  { skip: !live || !output, timeout: 45_000 }, async (t) => {
    assert.match(live, /^http:\/\/127\.0\.0\.1:\d+$/);
    await mkdir(output, { recursive: true });
    const browser = await launch();
    t.after(() => browser.close());
    for (const [label, viewport] of [['desktop', { width: 1440, height: 1000 }],
      ['mobile', { width: 390, height: 844 }]]) {
      const page = await browser.newPage({ viewport });
      page.setDefaultTimeout(10_000);
      await page.goto(live);
      await page.getByRole('status').filter({ hasText: 'GitHub sources checked' }).waitFor();
      await page.getByRole('heading', { name: 'Latest validation' }).waitFor();
      assert.ok(await page.getByRole('link', { name: 'Artifacts' }).count() > 0);
      await noHorizontalOverflow(page);
      await page.screenshot({ path: join(output, `dashboard-${label}.png`), fullPage: true });
      if (label === 'desktop') {
        await page.getByRole('navigation').getByRole('link', { name: 'HomeCI' }).click();
        await page.locator('summary').first().click();
        await page.getByRole('link', { name: 'Job log' }).first().waitFor();
        await page.locator('summary').first().blur();
        await page.screenshot({ path: join(output, 'homeci-desktop.png'), fullPage: true });
      } else {
        await page.getByRole('navigation').getByRole('link', { name: 'Development' }).click();
        await page.getByRole('link', { name: 'Plan source' }).waitFor();
        await page.getByRole('heading', { level: 1 }).blur();
        await page.screenshot({ path: join(output, 'development-mobile.png') });
      }
      await page.close();
    }
  });

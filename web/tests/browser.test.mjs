import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';
import { missionControl } from '../server.mjs';
import { commit, entry, githubFixture, job, listen, password, run, title, token } from './fixtures.mjs';

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
  await page.getByRole('heading', { name: 'DAF roadmap' }).waitFor();
  await page.getByText('Status unknown', { exact: true }).waitFor();
  assert.match(await page.getByRole('link', { name: 'M1.2 review evidence' }).getAttribute('href'),
    /\/blob\/[a-f0-9]{40}\/docs\/m1\.2-validation\.md$/);

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

test('appearance follows the OS, persists locally and keeps readable keyboard controls', { timeout: 30_000 }, async (t) => {
  const app = missionControl({ repositories: [entry] }, { fetcher: githubFixture });
  let browser;
  t.after(async () => { try { await browser?.close(); } finally { await app.stop(); } });
  const origin = await listen(app);
  browser = await launch();
  const page = await browser.newPage({ colorScheme: 'dark', reducedMotion: 'reduce',
    viewport: { width: 390, height: 844 } });
  page.setDefaultTimeout(5_000);
  const appearance = page.getByLabel('Appearance');
  const canvas = () => page.locator('html').evaluate((root) => getComputedStyle(root).backgroundColor);
  await page.goto(origin);
  await page.getByText('GitHub sources checked', { exact: false }).waitFor();
  assert.equal(await appearance.inputValue(), 'system');
  assert.equal(await canvas(), 'rgb(11, 20, 17)');
  await page.emulateMedia({ colorScheme: 'light' });
  assert.equal(await canvas(), 'rgb(245, 246, 241)');
  for (let i = 0; i < 10 && !await appearance.evaluate((el) => el === document.activeElement); i++) {
    await page.keyboard.press('Tab');
  }
  assert.ok(await appearance.evaluate((el) => el === document.activeElement));
  assert.equal(await appearance.evaluate((el) => getComputedStyle(el).outlineStyle), 'solid');
  for (const theme of ['dark', 'light']) {
    await appearance.selectOption(theme);
    await page.reload();
    assert.equal(await appearance.inputValue(), theme);
    assert.equal(await canvas(), theme === 'dark' ? 'rgb(11, 20, 17)' : 'rgb(245, 246, 241)');
    assert.deepEqual(await page.evaluate(() => ({ ...localStorage })), { 'daf.appearance': theme });
    await noHorizontalOverflow(page);
    await page.getByText('GitHub sources checked', { exact: false }).waitFor();
    const contrast = await page.locator('.badge').evaluateAll((badges) => {
      function luminance(value) {
        const channels = value.match(/\d+(?:\.\d+)?/g).slice(0, 3).map((n) => Number(n) / 255);
        const linear = channels.map((c) => c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
        return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
      }
      return badges.map((item) => {
        const style = getComputedStyle(item);
        const a = luminance(style.color);
        const b = luminance(style.backgroundColor);
        return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      });
    });
    assert.ok(contrast.length > 0 && contrast.every((ratio) => ratio >= 4.5), `${theme}: ${contrast}`);
  }
  await appearance.selectOption('system');
  await page.emulateMedia({ colorScheme: 'dark' });
  assert.equal(await canvas(), 'rgb(11, 20, 17)');
  assert.equal(await page.evaluate(() => document.getAnimations().length), 0);
});

test('authenticated Actions-only HomeCI displays exact evidence and keeps the token server-side', { timeout: 30_000 }, async (t) => {
  const repository = 'samuelwhite/forge-homeci';
  const calls = [];
  const app = missionControl({ repositories: [{ repository, visibility: 'private', planning: false }],
    password, token }, { fetcher: async (url, options) => {
    calls.push(new URL(url).pathname);
    assert.equal(options.headers.Authorization, `Bearer ${token}`);
    assert.equal(options.method, 'GET');
    return githubFixture(url);
  } });
  let browser;
  t.after(async () => { try { await browser?.close(); } finally { await app.stop(); } });
  const origin = await listen(app);
  assert.equal((await fetch(origin + '/api/mission-control')).status, 401);
  browser = await launch();
  const page = await browser.newPage({ httpCredentials: { username: 'daf', password } });
  page.setDefaultTimeout(5_000);
  const feed = page.waitForResponse((response) => response.url() === origin + '/api/mission-control' && response.ok());
  await page.goto(origin + '/#homeci');
  assert.ok(!(await (await feed).text()).includes(token));
  await page.getByText('Run 123 · Attempt 2', { exact: true }).waitFor();
  assert.equal(await page.getByRole('link', { name: `Commit ${commit}` }).getAttribute('href'),
    `https://github.com/${repository}/commit/${commit}`);
  await page.getByText('1 of 1 jobs shown').click();
  await page.getByText('Job 456', { exact: true }).waitFor();
  assert.equal(await page.getByRole('link', { name: 'Job log' }).getAttribute('href'),
    `https://github.com/${repository}/actions/runs/123/job/456`);
  await page.getByText('Runner observed on this job:', { exact: false }).waitFor();
  await page.getByText('Health unknown', { exact: true }).waitFor();
  assert.deepEqual(calls, [`/repos/${repository}/actions/runs`,
    `/repos/${repository}/actions/runs/123/attempts/2/jobs`]);
});

test('HomeCI shows the candidate PR, queued state and exact verification result', { timeout: 30_000 }, async (t) => {
  const repository = 'samuelwhite/forge-homeci';
  const candidate = 'b'.repeat(40);
  const runner = 'fixture-runner';
  const privateRepo = { full_name: repository };
  const makeRun = (id, status, conclusion, attempt = 1) => ({
    ...run, id, run_attempt: attempt, status, conclusion,
    path: '.github/workflows/daf-documentation-candidate.yml',
    name: 'DAF documentation candidate on HomeCI', event: 'workflow_dispatch',
    display_title: `DAF docs ${String(id).repeat(64).slice(0, 64)} PR ${id} at ${candidate}`,
    repository: privateRepo, head_repository: privateRepo,
  });
  const runs = [makeRun(3, 'completed', 'success'), makeRun(4, 'queued', null),
    makeRun(5, 'completed', 'cancelled'), makeRun(6, 'completed', 'success', 2)];
  const steps = [
    'Check dispatch inputs and runner identity', 'Check out the reviewed DAF baseline',
    'Verify one documentation change and exact checkout', 'Run portable contracts on the candidate',
    'Run supervised handoff and receipt regressions', 'Record candidate verification outcome',
  ].map((name) => ({ name, status: 'completed', conclusion: 'success' }));
  const app = missionControl({
    repositories: [{ repository, visibility: 'private', planning: false,
      homeciCandidate: { workflowId: run.workflow_id, workflowRevision: commit, runner } }],
    password, token,
  }, { fetcher: async (url) => {
    const parts = new URL(url).pathname.split('/');
    if (parts.at(-1) === 'runs') return Response.json({ workflow_runs: runs });
    const selected = runs.find(({ id }) => String(id) === parts.at(-4));
    if (selected?.id !== 3) return Response.json({ total_count: 0, jobs: [] });
    return Response.json({ total_count: 1, jobs: [{
      ...job, run_id: selected.id, run_attempt: selected.run_attempt, name: selected.name,
      conclusion: 'success', runner_name: runner, steps,
    }] });
  } });
  let browser;
  t.after(async () => { try { await browser?.close(); } finally { await app.stop(); } });
  const origin = await listen(app);
  browser = await launch();
  const page = await browser.newPage({ httpCredentials: { username: 'daf', password } });
  await page.goto(origin + '/#homeci');
  const pr = page.getByRole('link', { name: 'DAF PR #3', exact: true });
  assert.equal(await pr.getAttribute('href'), 'https://github.com/samuelwhite/development-autonomy-framework/pull/3');
  await page.getByText('GitHub reports the exact checkout and both suites passed.', { exact: false }).waitFor();
  await page.getByText('Waiting for GitHub to assign the job', { exact: true }).waitFor();
  await page.getByText('Workflow cancelled', { exact: true }).waitFor();
  await page.getByText('Only the original run attempt is eligible', { exact: true }).waitFor();
  await page.getByText('1 of 1 jobs shown').click();
  await page.getByText(`Runner observed on this job: ${runner}`, { exact: false }).waitFor();
  assert.equal(await page.getByRole('link', { name: 'Job log' }).getAttribute('href'),
    `https://github.com/${repository}/actions/runs/3/job/${job.id}`);
  await noHorizontalOverflow(page);
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
      if (label === 'desktop') {
        await page.getByRole('navigation').getByRole('link', { name: 'HomeCI' }).click();
        await page.locator('summary').first().click();
        await page.getByRole('link', { name: 'Job log' }).first().waitFor();
        await page.locator('summary').first().blur();
      } else {
        await page.getByRole('navigation').getByRole('link', { name: 'Development' }).click();
        await page.getByRole('link', { name: 'Plan source' }).waitFor();
        await page.getByRole('heading', { level: 1 }).blur();
      }
      for (const theme of ['light', 'dark']) {
        const appearance = page.getByLabel('Appearance');
        await appearance.selectOption(theme);
        await appearance.blur();
        await noHorizontalOverflow(page);
        await page.screenshot({ path: join(output, `ui02-${label}-${theme}.png`), fullPage: true });
      }
      await page.close();
    }
  });

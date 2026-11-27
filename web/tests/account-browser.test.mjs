import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { copyFile, mkdir, mkdtemp, rm } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { bootstrapAccounts } from '../accounts.mjs';
import { missionControl } from '../server.mjs';
import { listen, password } from './fixtures.mjs';

const { chromium } = createRequire(new URL('../../desktop/package.json', import.meta.url))('playwright');
const output = process.env.DAF_ACCOUNTS_SCREENSHOTS;
const channel = process.env.DAF_WEB_BROWSER_CHANNEL;
const adminPassword = 'copper lanterns light the old signal tower';
const viewerPassword = 'several rivers cross the valley before dawn';
const changedPassword = 'river stones keep the memory of rain';
const resetPassword = 'orchard paths circle back through sunlight';
const viewer = 'first.last+development@engineering.example.test';

test('administrator and viewer use local accounts in the browser', { timeout: 60_000 }, async (t) => {
  const directory = await mkdtemp(join(tmpdir(), 'daf-account-browser-'));
  let app;
  let browser;
  t.after(async () => {
    try { await browser?.close(); } finally {
      try { await app?.stop(); } finally { await rm(directory, { recursive: true, force: true }); }
    }
  });
  await bootstrapAccounts(directory, 'demo.admin', adminPassword);
  const rehearsal = join(directory, 'pilot');
  const script = fileURLToPath(new URL('../../scripts/rehearse_document_pilot.py', import.meta.url));
  const report = JSON.parse(execFileSync(process.env.PYTHON || 'python', [script, rehearsal],
    { encoding: 'utf8', timeout: 20000 }));
  assert.deepEqual(report.external_writes, { branch: 1, draft: 1, dispatch: 1 });
  const reserved = createServer();
  await new Promise((resolve) => reserved.listen(0, '127.0.0.1', resolve));
  const { port } = reserved.address();
  await new Promise((resolve) => reserved.close(resolve));
  const origin = `http://127.0.0.1:${port}`;
  app = missionControl({ repositories: [
    { repository: 'example/daf', visibility: 'public', planning: false },
    { repository: 'example/validator', visibility: 'private', planning: false },
  ], host: '127.0.0.1', authMode: 'accounts', token: 'fixture-only',
  authDirectory: directory, publicOrigin: origin, pilotFile: join(rehearsal, 'journal', 'document-pilot.json'),
  }, { fetcher: async () => Response.json({ workflow_runs: [] }) });
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
    await page.getByRole('textbox', { name: 'Username or email' }).fill(name);
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
  const identifier = add.getByLabel('Username or email');
  await identifier.fill('invalid.@example.test');
  await add.getByLabel('Password', { exact: true }).fill(viewerPassword);
  await add.getByRole('button', { name: 'Add user' }).click();
  await add.getByRole('alert').filter({ hasText: 'Use a 3 to 32 character username or a valid email address.' }).waitFor();
  await identifier.fill(viewer.toUpperCase());
  assert.equal(await identifier.inputValue(), viewer.toUpperCase());
  await add.getByRole('button', { name: 'Add user' }).click();
  await desktop.getByRole('heading', { name: viewer }).waitFor();
  await capture(desktop, 'desktop-users');

  await signIn(phone, viewer.toUpperCase(), viewerPassword);
  assert.equal(await phone.getByRole('link', { name: 'Settings / Users' }).count(), 0);
  assert.equal((await phone.request.get(origin + '/settings/users')).status(), 403);
  for (const view of ['Development', 'HomeCI']) {
    await phone.getByRole('link', { name: view, exact: true }).click();
    const pilot = phone.getByRole('heading', { name: 'Documentation pilot' }).locator('..').locator('..');
    await pilot.getByText('Ready for review', { exact: true }).waitFor();
    await pilot.getByText(report.observation.candidate_sha, { exact: true }).waitFor();
    await pilot.getByText('Attempt operator-guide-1 · docs/guide.md', { exact: true }).waitFor();
    await pilot.getByText('Run 1401 · Attempt 1 · Job 1601 · demo-runner · success', { exact: true }).waitFor();
    assert.equal(await pilot.getByRole('link', { name: 'PR #28' }).getAttribute('href'),
      'https://github.com/example/daf/pull/28');
    assert.equal(await pilot.getByRole('link', { name: 'Job log' }).getAttribute('href'),
      'https://github.com/example/validator/actions/runs/1401/job/1601');
    assert.equal(await pilot.getByRole('button').count(), 0);
    await capture(phone, `phone-pilot-${view.toLowerCase()}`);
  }
  assert.equal((await phone.request.post(origin + '/api/mission-control')).status(), 405);
  await phone.getByRole('link', { name: 'My account' }).click();
  await phone.getByRole('heading', { name: 'Change password' }).waitFor();
  await phone.locator('#account-identity').filter({ hasText: viewer }).waitFor();
  assert.ok(await noOverflow(phone));
  await phone.getByLabel('Current password').fill(viewerPassword);
  await phone.getByLabel('New password').fill(changedPassword);
  await phone.getByRole('button', { name: 'Change password' }).click();
  await phone.getByRole('heading', { name: 'Sign in to Mission Control' }).waitFor();
  await signIn(phone, viewer, changedPassword);
  await desktop.getByLabel(`Reset password for ${viewer}`).click();
  const reset = desktop.locator('details[open] form');
  await reset.getByLabel('New password').fill(resetPassword);
  await reset.getByRole('button', { name: 'Set password' }).click();
  await desktop.getByText(`Password reset for ${viewer}.`, { exact: true }).waitFor();
  assert.equal((await phone.request.get(origin + '/api/mission-control')).status(), 401);
  await desktop.getByRole('button', { name: `Disable ${viewer}` }).click();
  await desktop.getByRole('button', { name: `Enable ${viewer}` }).waitFor();
  await desktop.getByRole('button', { name: 'Sign out' }).click();
  await desktop.getByRole('heading', { name: 'Sign in to Mission Control' }).waitFor();
  assert.equal((await desktop.request.get(origin + '/api/mission-control')).status(), 401);
});

test('code rehearsal shows the same reserved run through recovery, and retains failure', { timeout: 60_000 }, async (t) => {
  const directory = await mkdtemp(join(tmpdir(), 'daf-code-browser-'));
  const pilotFile = join(directory, 'document-pilot.json');
  let app;
  let browser;
  t.after(async () => {
    try { await browser?.close(); } finally {
      try { await app?.stop(); } finally { await rm(directory, { recursive: true, force: true }); }
    }
  });
  const script = fileURLToPath(new URL('../../scripts/rehearse_code_pilot.py', import.meta.url));
  const work = join(directory, 'rehearsal');
  const run = async (workspace, expected, ...options) => {
    const result = spawnSync(process.env.PYTHON || 'python', [script, workspace, ...options],
      { encoding: 'utf8', timeout: 20000 });
    assert.equal(result.status, expected, result.stderr || result.error?.message);
    const report = JSON.parse(result.stdout);
    assert.deepEqual(report.external_writes, { branch: 1, draft: 1, dispatch: 1 });
    await copyFile(join(workspace, 'journal', 'document-pilot.json'), pilotFile);
    return report.observation;
  };
  const incomplete = await run(work, 1, '--scenario', 'incomplete-metadata');
  app = missionControl({
    repositories: [
      { repository: 'example/daf', visibility: 'public', planning: false },
      { repository: 'example/validator', visibility: 'private', planning: false },
    ], host: '127.0.0.1', password, token: 'fixture-only', pilotFile,
  }, { fetcher: async () => Response.json({ workflow_runs: [] }) });
  const origin = await listen(app);
  assert.equal((await fetch(origin + '/api/mission-control')).status, 401);
  browser = await chromium.launch(channel ? { channel } : {});
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 },
    httpCredentials: { username: 'daf', password } });
  page.setDefaultTimeout(6000);
  await page.goto(origin);

  const checkViews = async (observation, status, metadata, state) => {
    for (const view of ['Development', 'HomeCI']) {
      await page.getByRole('link', { name: view, exact: true }).click();
      const pilot = page.getByRole('heading', { name: 'Code rehearsal' }).locator('..').locator('..');
      await pilot.getByText(status, { exact: true }).waitFor();
      await pilot.getByText(observation.candidate_sha, { exact: true }).waitFor();
      await pilot.getByText('Attempt normalize-label-1 · src/label.py', { exact: true }).waitFor();
      await pilot.getByText(metadata, { exact: true }).waitFor();
      await pilot.getByText('Simulated PR #28', { exact: true }).waitFor();
      assert.equal(await pilot.getByRole('link').count(), 0);
      assert.equal(await pilot.getByRole('button').count(), 0);
      if (output) {
        await mkdir(output, { recursive: true });
        await page.screenshot({ path: join(output, 'code-' + view.toLowerCase() + '-' + state + '.png') });
      }
    }
  };
  await checkViews(incomplete, 'Blocked', 'Reserved simulated run 1401', 'incomplete');
  assert.equal(await page.getByRole('link', { name: 'Job log', exact: true }).count(), 0);
  const recovered = await run(work, 0);
  assert.equal(recovered.candidate_sha, incomplete.candidate_sha);
  assert.equal(recovered.run_id, incomplete.run_id);
  await page.getByRole('button', { name: 'Refresh view' }).click();
  await checkViews(recovered, 'Ready for review',
    'Simulated run 1401 · Attempt 1 · Simulated job 1601 · demo-runner · success', 'accepted');
  const failed = await run(join(directory, 'failed-rehearsal'), 1, '--scenario', 'failed');
  await page.getByRole('button', { name: 'Refresh view' }).click();
  await checkViews(failed, 'Needs attention',
    'Simulated run 1401 · Attempt 1 · Simulated job 1601 · demo-runner · failure', 'failed');
  await page.getByText('The focused Python test failed.', { exact: true }).waitFor();
  assert.equal((await page.request.post(origin + '/api/mission-control')).status(), 405);
});

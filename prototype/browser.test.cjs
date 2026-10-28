// Optional browser QA: DAF_PLAYWRIGHT_PATH may point to an existing Playwright package.
// No browser/package download is performed. Use an already installed Chromium.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { pathToFileURL } = require('node:url');
const { chromium } = require(process.env.DAF_PLAYWRIGHT_PATH || 'playwright');
const url = pathToFileURL(path.join(__dirname, 'index.html')).href;
const out = process.env.DAF_UI_ARTIFACT_DIR;

test('offline browser journey, controls, recovery and responsive layout', { timeout: 90000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({ offline: true, viewport: { width: 1440, height: 1000 } });
    const page = await context.newPage();
    const errors = [];
    const external = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => { if (!request.url().startsWith('file:')) external.push(request.url()); });
    async function click(name) { await page.getByRole('button', { name, exact: true }).click(); }
    async function setup(provider = 'codex', mode = 'review', injection = false) {
      await page.goto(url);
      await click('Let’s get set up →');
      await page.locator(`input[name="provider"][value="${provider}"]`).check();
      await click('Continue →');
      await click(provider === 'codex' ? 'Simulate browser sign-in' : 'Simulate API connection');
      await click('Continue →'); await click('Continue →');
      await page.locator(`input[name="mode"][value="${mode}"]`).check();
      await click('Continue →');
      await click('Try a failed check');
      assert.equal(await page.getByRole('button', { name: 'Continue →', exact: true }).isDisabled(), true);
      await click('Verify simulated connection'); await click('Continue →');
      await page.locator('#task').fill('  '); await click('Prepare my task →');
      assert.match(await page.locator('#task-error').textContent(), /Enter a short task/);
      await page.locator('#task').fill(injection ? '<img src=x onerror=alert(1)> Review the sample README' : 'Review the sample README and suggest a clearer getting-started section.');
      await click('Prepare my task →');
      assert.equal(await page.locator('main img').count(), 0);
    }
    if (out) {
      fs.mkdirSync(out, { recursive: true });
      await page.goto(url);
      await page.screenshot({ path: path.join(out, 'welcome.png'), fullPage: true });
    }
    await setup('codex', 'review', true);
    await click('Start simulation');
    await page.getByText('SIMULATION COMPLETE', { exact: true }).waitFor();
    assert.match(await page.locator('main').textContent(), /No write permission was requested/);
    await click('Set up another simulation');
    await setup('claude', 'edit');
    await click('Start simulation');
    await page.getByRole('button', { name: 'Approve sample edit once' }).waitFor();
    if (out) await page.screenshot({ path: path.join(out, 'mission-control.png'), fullPage: true });
    await page.reload();
    await page.getByText('OUTCOME UNKNOWN · BLOCKED', { exact: true }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Set up another simulation', exact: true }).isDisabled(), true);
    await click('■ Stop task');
    assert.equal(await page.getByText('OUTCOME UNKNOWN · BLOCKED', { exact: true }).count(), 1);
    await click('Reconcile existing attempt');
    await page.getByText('STOPPED', { exact: true }).waitFor();
    assert.match(await page.locator('.timeline').textContent(), /No duplicate attempt/);
    await click('Set up another simulation');
    await setup('codex', 'edit');
    await page.getByText('Try a failure scenario', { exact: true }).click();
    await page.locator('[name="scenario"]').selectOption('check-failure');
    await click('Start simulation');
    await click('Approve sample edit once');
    await page.getByText('CHECK FAILED · BLOCKED', { exact: true }).waitFor();
    await click('Set up another simulation');
    await setup('codex', 'edit'); await click('Start simulation');
    await click('Deny and stop');
    await page.getByText('STOPPED', { exact: true }).waitFor();
    await click('Set up another simulation');
    await setup('codex', 'edit'); await click('Start simulation');
    await click('Approve sample edit once');
    await page.getByText('SIMULATION COMPLETE', { exact: true }).waitFor();
    await click('Set up another simulation');
    await setup(); await click('Start simulation'); await click('■ Stop task');
    await page.waitForTimeout(3000);
    assert.equal(await page.getByText('STOPPED', { exact: true }).count(), 1);
    await click('Set up another simulation');
    await page.setViewportSize({ width: 390, height: 844 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    if (out) await page.screenshot({ path: path.join(out, 'mobile.png'), fullPage: true });
    await setup('claude', 'edit'); await click('Start simulation');
    await page.getByRole('button', { name: 'Approve sample edit once' }).waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await click('■ Stop task');
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    await context.close();
    const noStorage = await browser.newContext({ offline: true });
    await noStorage.addInitScript(() => {
      Object.defineProperty(window, 'sessionStorage', { get() { throw new Error('Storage disabled'); } });
    });
    const fallback = await noStorage.newPage(); await fallback.goto(url);
    assert.match(await fallback.locator('main').textContent(), /storage is unavailable/);
    await fallback.getByRole('button', { name: 'Let’s get set up →', exact: true }).click();
    assert.equal(await fallback.getByRole('heading', { name: 'Who would you like to work with?' }).count(), 1);
    await noStorage.close();
  } finally { await browser.close(); }
});

// Optional browser QA; uses an existing Playwright package and installed Chromium.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
const { pathToFileURL } = require('node:url');
const { chromium } = require(process.env.DAF_PLAYWRIGHT_PATH || 'playwright');
const url = pathToFileURL(path.join(__dirname, 'index.html')).href;
const out = process.env.DAF_UI_ARTIFACT_DIR;

test('beginner journeys, automatic checks, workspace and safe recovery stay offline', { timeout: 180000 }, async () => {
  const browser = await chromium.launch({ headless: true });
  const errors = [], external = [];
  try {
    const context = await browser.newContext({ offline: true, viewport: { width: 1440, height: 1000 } });
    let page;
    async function fresh() {
      if (page) await page.close();
      page = await context.newPage();
      page.on('pageerror', error => errors.push(error.message));
      page.on('request', request => { if (!request.url().startsWith('file:')) external.push(request.url()); });
      await page.goto(url);
    }
    async function click(name) { await page.getByRole('button', { name, exact: true }).click(); }
    async function snap(name) {
      if (out) {
        fs.mkdirSync(out, { recursive: true });
        await page.screenshot({ path: path.join(out, `${name}.png`), fullPage: true });
      }
    }
    async function nav(name) { await page.getByRole('navigation', { name: 'Workspace', exact: true }).locator(`[data-view="${name.toLowerCase()}"]`).click(); }
    async function setup(provider = 'codex', mode = 'review', issue = 'none', project = 'Fieldnotes') {
      await fresh(); await click('Let’s get started →');
      assert.equal(await page.locator('[name="provider"]:checked').count(), 0);
      assert.equal(await page.getByRole('button', { name:'Continue →', exact:true }).isDisabled(), true);
      await page.locator(`[name="provider"][value="${provider}"]`).check();
      await click('Continue →');
      assert.match(await page.locator('main').textContent(), /demo connection/);
      await click('Try the demo connection →');
      assert.match(await page.locator('main').textContent(), /This demo cannot open your files/);
      await page.locator(`[name="project"][value="${project}"]`).check();
      await click('Continue →');
      assert.equal(await page.locator('[name="mode"][value="review"]').isChecked(), true);
      await page.locator(`[name="mode"][value="${mode}"]`).check();
      assert.equal(await page.locator('[name="tokens"]').isVisible(), false);
      if (issue !== 'none') {
        await page.getByText('Explore a setup problem (optional demo)', { exact:true }).click();
        await page.locator('[name="setupIssue"]').selectOption(issue);
      }
      await click('Continue →');
      if (issue === 'none') await page.getByRole('heading', { name:'Start with a useful little task', exact:true }).waitFor();
      else await page.getByRole('heading', { name:'One thing needs your attention', exact:true }).waitFor();
    }
    async function start(kind = 'documentation', scenario = 'normal') {
      await page.locator(`[name="taskKind"][value="${kind}"]`).check();
      if (scenario !== 'normal') {
        await page.getByText('Explore a task problem (optional demo)', { exact:true }).click();
        await page.locator('[name="scenario"]').selectOption(scenario);
      }
      await click('Start example task →');
      await page.getByRole('navigation', { name:'Workspace', exact:true }).waitFor();
      assert.equal(await page.getByRole('navigation', { name:'Setup progress', exact:true }).count(), 0);
    }
    async function status(text) { await page.locator('.status-badge').filter({hasText:text}).waitFor(); }
    // Keyboard-only assistant selection has no default and retains focus on redraw.
    await fresh(); await snap('welcome'); await click('Let’s get started →'); await snap('assistants');
    await page.locator('[name="provider"][value="codex"]').focus(); await page.keyboard.press('Space');
    assert.equal(await page.locator('[name="provider"][value="codex"]').isChecked(), true);
    await page.keyboard.press('ArrowRight');
    assert.equal(await page.locator('[name="provider"][value="claude"]').isChecked(), true);
    assert.equal(await page.evaluate(() => document.activeElement.value), 'claude');
    await click('Continue →'); await click('Try the demo connection →'); await snap('projects');
    await click('Continue →'); await snap('permissions'); await click('Continue →');
    await page.getByRole('heading', {name:'Start with a useful little task'}).waitFor(); await snap('starter-tasks');
    await start(); await status('Making progress'); await snap('mission-running');
    await page.locator('[data-disclosure="usage"] summary').focus(); await page.keyboard.press('Enter');
    await page.waitForTimeout(2000);
    assert.equal(await page.evaluate(() => document.activeElement.dataset.focus), 'disclosure-usage');
    assert.equal(await page.locator('[data-disclosure="usage"]').getAttribute('open'), '');
    await page.keyboard.press('Enter');
    await status('Task complete');
    assert.match(await page.locator('main').textContent(), /3 of 3 milestones completed/);
    assert.match(await page.locator('main').textContent(), /Nothing was changed/);
    assert.equal(await page.getByRole('button', {name:'Allow this example change', exact:true}).count(), 0);
    await snap('mission-control');
    await nav('Results'); assert.match(await page.locator('main').textContent(), /Getting started with Fieldnotes/);
    await page.reload(); assert.match(await page.locator('main').textContent(), /Welcome back/);
    assert.equal(await page.getByRole('heading', {name:'Your latest result', exact:true}).count(), 1);
    await nav('Activity'); assert.match(await page.locator('main').textContent(), /Your suggestions are ready/);
    // Both providers and each starter have a concrete result with no custom prompt.
    await setup('codex', 'edit', 'none', 'Little Library'); await start('review'); await status('Task complete');
    await nav('Results'); assert.match(await page.locator('main').textContent(), /book entry/);
    await setup('claude', 'edit'); await start('plan'); await status('Task complete');
    await nav('Results'); assert.match(await page.locator('main').textContent(), /not a queue of work/);
    // Every setup failure has a reason, a precise fix, Retry and help; retry alone cannot pass.
    for (const [issue, fix] of [['connection','Fix this: reconnect the demo'], ['permissions','Fix this: use suggestions only'], ['limits','Fix this: restore recommended limits']]) {
      await setup('claude', 'edit', issue);
      assert.match(await page.getByRole('alert').textContent(), /What to do:/);
      await page.getByText('Help with this check', {exact:true}).click();
      assert.equal(await page.locator('[data-disclosure="check-help"]').getAttribute('open'), '');
      if (issue === 'permissions') await snap('setup-attention');
      await click('Retry'); await page.getByRole('heading', {name:'One thing needs your attention'}).waitFor();
      assert.equal(await page.getByRole('button', {name:'Start example task →', exact:true}).count(), 0);
      await click(fix); await page.getByRole('heading', {name:'Start with a useful little task'}).waitFor();
      if (issue === 'permissions') assert.match(await page.locator('.summary-line').textContent(), /Suggestions only/);
    }
    // Back from an automatic check cannot cause a late advance or bypass changed settings.
    await setup(); await click('← Back'); await click('Continue →'); await click('← Back');
    await page.waitForTimeout(1000); assert.equal(await page.getByRole('heading', {name:'How would you like DAF to help?'}).count(), 1);
    // Edit approval is the only required interruption on the successful edit journey.
    await setup('claude', 'edit'); await start();
    await page.getByRole('button', {name:'Allow this example change', exact:true}).waitFor();
    await snap('approval');
    await page.getByRole('link', {name:'1 thing needs your attention ↓',exact:true}).click();
    const attentionBox = await page.locator('#attention').boundingBox();
    const headerBox = await page.locator('.dashboard-top').boundingBox();
    assert.ok(attentionBox.y >= headerBox.y + headerBox.height);
    assert.equal(await page.evaluate(() => document.activeElement.id), 'attention');
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.dataset.action), 'allow');
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
    const stopBox = await page.getByRole('button', {name:'■ Stop task', exact:true}).boundingBox();
    assert.ok(stopBox.y >= 0 && stopBox.y + stopBox.height <= 1000);
    await click('Allow this example change'); await status('Task complete');
    assert.match(await page.locator('main').textContent(), /approved this one example change/);
    // Denial and immediate stop prevent later timer callbacks from continuing.
    await setup('codex', 'edit'); await start(); await click('No, stop here'); await status('Work stopped');
    await setup(); await start(); await click('■ Stop task'); await page.waitForTimeout(4000);
    await status('Work stopped'); assert.equal(await page.locator('[data-action="allow"]').count(), 0);
    // Reload during an approval: retained allowance, failed recovery, explicit fix, no duplicate task.
    await setup('claude', 'edit'); await start();
    await page.getByRole('button', {name:'Allow this example change', exact:true}).waitFor();
    await page.reload(); await status('Earlier work needs checking'); await snap('recovery');
    await nav('Settings'); assert.equal(await page.getByRole('button',{name:'Start over',exact:true}).isDisabled(), true);
    await page.getByText('Explore demo problems', {exact:true}).click();
    await page.locator('[name="recoveryUnavailable"]').check();
    await nav('Overview'); await click('Check earlier work');
    await page.getByRole('heading', {name:'We still couldn’t confirm what happened'}).waitFor();
    await click('Retry'); await status('Earlier work needs checking');
    await click('■ Stop task'); await status('Earlier work needs checking');
    await click('Fix this: make the demo result available'); await status('Work stopped');
    const saved = await page.evaluate(() => JSON.parse(sessionStorage.getItem('daf-v02-offline-prototype')));
    assert.equal(saved.attempt, 1); assert.equal(saved.reserved, 0);
    // Result failure, budget refusal and interrupted connection have actionable explanations.
    for (const [scenario, expected] of [['check-failure','Result needs attention'], ['limit','Task limit reached'], ['connection-lost','Earlier work needs checking']]) {
      await setup(); await start('documentation', scenario); await status(expected);
      assert.match(await page.getByRole('alert').textContent(), /What to do:/);
    }
    // Custom text is optional, validated and escaped; demo results are not claimed as model output.
    await setup('codex', 'edit');
    await page.getByText('Prefer to write your own task?', {exact:true}).click(); await click('Use my own words');
    await click('Start example task →'); assert.match(await page.locator('#task-error').textContent(), /short task/);
    await page.locator('#customTask').fill('<img src=x onerror=alert(1)> A custom idea');
    await click('Start example task →'); assert.equal(await page.locator('main img').count(), 0);
    await click('■ Stop task');
    // Narrow layout, reachable workspace navigation, readable text, keyboard-operable disclosures.
    await setup('claude', 'edit'); await page.setViewportSize({width:390,height:844}); await start();
    await page.getByRole('button', {name:'Allow this example change', exact:true}).waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await snap('mobile'); await nav('Settings');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.locator('[data-disclosure="workspace-demo"] summary').focus(); await page.keyboard.press('Enter');
    await click('Reach the time limit'); await status('Work stopped');
    assert.match(await page.locator('main').textContent(), /time limit stopped/);
    await nav('Settings'); await click('Start over');
    assert.equal(await page.getByRole('navigation',{name:'Setup progress',exact:true,includeHidden:true}).count(), 1);
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    await context.close();
    const noStorage = await browser.newContext({offline:true});
    await noStorage.addInitScript(() => Object.defineProperty(window, 'sessionStorage', {get() {throw new Error('Storage disabled');}}));
    const fallback = await noStorage.newPage(); await fallback.goto(url);
    assert.match(await fallback.locator('main').textContent(), /cannot save demo progress/);
    await fallback.getByRole('button', {name:'Let’s get started →',exact:true}).click();
    assert.equal(await fallback.getByRole('heading',{name:'Choose your AI assistant'}).count(), 1);
    await noStorage.close();
  } finally { await browser.close(); }
});

import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { get } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { loadConfig, validateRepositories } from '../config.mjs';
import { createFeed } from '../feed.mjs';
import { missionControl } from '../server.mjs';
import { baseline, commit, entry, file, githubFixture, job, listen, password, plan, run, title, token } from './fixtures.mjs';

const config = (repositories = [entry]) => ({ repositories: validateRepositories(repositories) });
const signal = () => new AbortController().signal;
const authorization = `Basic ${Buffer.from(`daf:${password}`).toString('base64')}`;

test('operator allowlist rejects URL, traversal, aliases, mutable refs and invalid configuration', async (t) => {
  for (const repository of ['https://github.com/example/project', 'owner/..', 'a/b%2f..', 'a/b?x=1', 'a/b/c']) {
    assert.throws(() => validateRepositories([{ ...entry, repository }]), /Invalid repository/);
  }
  assert.throws(() => validateRepositories([entry, { ...entry, repository: 'EXAMPLE/PROJECT' }]), /Duplicate/);
  for (const plan of [{ ...entry.plan, commit: 'main' }, { ...entry.plan, path: 'a/../x.json' }]) {
    assert.throws(() => validateRepositories([{ ...entry, plan }]), /Invalid pinned/);
  }
  const dir = await mkdtemp(join(tmpdir(), 'daf-web-config-'));
  t.after(() => rm(dir, { recursive: true }));
  const path = join(dir, 'sources.json');
  await writeFile(path, JSON.stringify([{ ...entry, visibility: 'private' }]));
  const env = { DAF_REPOSITORIES_FILE: path };
  assert.throws(() => loadConfig(env), /viewer authentication/);
  const secret = join(dir, 'viewer');
  await writeFile(secret, `${password}\n`);
  assert.equal(loadConfig({ ...env, DAF_VIEWER_PASSWORD_FILE: secret }).password, password);
  await writeFile(secret, '');
  assert.throws(() => loadConfig({ ...env, DAF_VIEWER_PASSWORD_FILE: secret }), /secret configuration/);
  assert.equal(loadConfig({}).host, '127.0.0.1');
});

test('HTTP routes, methods, credentials and GitHub provenance are bounded', async (t) => {
  const calls = [];
  const app = missionControl({ ...config(), token }, { fetcher: async (url, options) => {
    calls.push(new URL(url));
    assert.equal(options.method, 'GET');
    assert.equal(options.redirect, 'error');
    assert.equal(options.headers.Authorization, undefined);
    return githubFixture(url);
  } });
  t.after(() => app.stop());
  const origin = await listen(app);
  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']) {
    const response = await fetch(`${origin}/api/mission-control`, { method });
    assert.equal(response.status, 405);
    assert.equal(response.headers.get('allow'), 'GET, HEAD');
  }
  for (const path of ['/config.mjs', '/.env', '/api/mission-control?repo=evil/test', '/api/dispatch']) {
    assert.equal((await fetch(origin + path)).status, 404);
  }
  assert.equal((await fetch(`${origin}/api/mission-control`, { method: 'HEAD' })).status, 200);
  assert.equal(await (await fetch(`${origin}/healthz`)).text(), 'ok');
  assert.equal(calls.length, 0);
  const response = await fetch(`${origin}/api/mission-control`);
  assert.match(response.headers.get('content-security-policy'), /frame-ancestors 'none'/);
  assert.equal(response.headers.get('cache-control'), 'no-store');
  assert.equal(response.headers.get('access-control-allow-origin'), null);
  const raw = await response.text();
  assert.ok(!raw.includes('javascript:alert') && !raw.includes('example.invalid') && !raw.includes(token));
  const [project] = JSON.parse(raw).projects;
  assert.equal(project.issues.data[0].title, title);
  assert.equal(project.issues.data.length, 1);
  assert.equal(project.proposal.data.commit, commit);
  assert.equal(project.proposal.data.baseline, baseline);
  assert.equal(project.pulls.data[0].commitUrl, `https://github.com/example/project/pull/6/commits/${commit}`);
  assert.equal(project.runs.data[0].url, 'https://github.com/example/project/actions/runs/123/attempts/2');
  assert.equal(project.runs.data[0].workflowUrl, 'https://github.com/example/project/actions/workflows/ci.yml');
  assert.equal(project.runJobs[0].jobs.data.items[0].url, 'https://github.com/example/project/actions/runs/123/job/456');
  assert.equal(project.runJobs[0].jobs.data.items[0].selfHosted, true);
  assert.ok(calls.every((url) => url.origin === 'https://api.github.com' && url.pathname.startsWith('/repos/example/project/')));
  assert.ok(calls.some((url) => url.searchParams.get('ref') === commit));
  assert.equal(calls.length, 6);
});

test('static pages and assets accept query strings behind viewer authentication', async (t) => {
  let calls = 0;
  const app = missionControl({ ...config(), password }, { fetcher: () => { calls++; } });
  t.after(() => app.stop());
  const origin = await listen(app);
  const headers = { authorization };
  for (const [path, type] of [
    ['/?utm_source=chatgpt.com', 'text/html; charset=utf-8'],
    ['/?utm_source=chatgpt.com&utm_medium=referral', 'text/html; charset=utf-8'],
    ['/style.css?v=1', 'text/css; charset=utf-8'],
    ['/app.js?v=1', 'text/javascript; charset=utf-8'],
  ]) {
    assert.equal((await fetch(origin + path)).status, 401, path);
    const response = await fetch(origin + path, { headers });
    assert.equal(response.status, 200, path);
    assert.equal(response.headers.get('content-type'), type);
  }
  for (const path of [
    '/missing?v=1', '/api/mission-control?utm_source=chatgpt.com', '/api/mission-control?repo=evil/test',
    '/unknown/../app.js?v=1', '//localhost/style.css?v=1',
  ]) {
    // Send the exact request target to avoid client-side URL normalisation.
    const status = await new Promise((resolve, reject) => {
      get(origin, { path, headers }, (response) => {
        response.resume();
        resolve(response.statusCode);
      }).on('error', reject);
    });
    assert.equal(status, 404, path);
  }
  assert.equal(calls, 0);
});

test('public-only wildcard listeners fail closed and protect every viewer route', async (t) => {
  assert.throws(() => loadConfig({ DAF_BIND: '0.0.0.0' }), /require viewer authentication/);
  const settings = { ...config(), host: '0.0.0.0' };
  assert.throws(() => missionControl(settings), /require viewer authentication/);
  const app = missionControl({ ...settings, password }, { fetcher: githubFixture });
  t.after(() => app.stop());
  const origin = await listen(app);
  for (const path of ['/', '/app.js', '/style.css', '/api/mission-control']) {
    const response = await fetch(origin + path);
    assert.equal(response.status, 401);
    assert.match(response.headers.get('www-authenticate'), /^Basic realm=/);
    assert.equal(response.headers.get('cache-control'), 'no-store');
  }
  assert.equal((await fetch(origin + '/healthz')).status, 200);
  const response = await fetch(origin + '/api/mission-control', { headers: { authorization } });
  assert.equal(response.status, 200);
  assert.match(response.headers.get('content-security-policy'), /frame-ancestors 'none'/);
  assert.equal((await response.json()).projects[0].runs.state, 'current');
});

test('private feeds fail closed, and unauthenticated requests do not start reads', async (t) => {
  const privateEntry = { ...entry, repository: 'example/private', visibility: 'private', planning: false, plan: undefined };
  const settings = config([entry, privateEntry]);
  assert.throws(() => missionControl({ ...settings, token }), /viewer authentication/);
  let privateCalls = 0;
  let publicCalls = 0;
  const app = missionControl({ ...settings, password, token }, { fetcher: async (url, init) => {
    if (url.includes('/example/private/')) {
      privateCalls++;
      assert.equal(init.headers.Authorization, `Bearer ${token}`);
      return new Response('upstream body contains secrets', { status: 404 });
    }
    publicCalls++;
    assert.equal(init.headers.Authorization, undefined);
    return githubFixture(url);
  } });
  t.after(() => app.stop());
  const origin = await listen(app);
  for (const path of ['/', '/style.css', '/api/mission-control']) {
    const response = await fetch(origin + path);
    assert.equal(response.status, 401);
    assert.match(response.headers.get('www-authenticate'), /^Basic realm=/);
  }
  assert.equal((await fetch(`${origin}/api/mission-control`, { headers: { authorization: 'Basic d3Jvbmc=' } })).status, 401);
  assert.equal(privateCalls + publicCalls, 0);
  const response = await fetch(`${origin}/api/mission-control`, { headers: { authorization } });
  const raw = await response.text();
  assert.ok(!raw.includes(token) && !raw.includes(password) && !raw.includes('upstream body'));
  const [publicProject, privateProject] = JSON.parse(raw).projects;
  assert.equal(publicProject.runs.state, 'current');
  assert.equal(privateProject.runs.reason, 'inaccessible');
  assert.equal(privateProject.runs.state, 'blocked');
  assert.equal(privateCalls, 1);
  const unconfigured = createFeed({ ...config([privateEntry]), signal: signal(), fetcher: () => {
    assert.fail('Missing private token must suppress reads');
  } });
  assert.deepEqual((await unconfigured()).projects[0].runs,
    { state: 'unconfigured', reason: 'missing-credential', observed: null, data: null });
});

test('transient source failure retains scoped stale observations, then expires them', async () => {
  let time = 0;
  let unavailable = false;
  let reads = 0;
  const feed = createFeed({ ...config(), signal: signal(), now: () => time, fetcher: async (url) => {
    reads++;
    if (unavailable && url.includes('/actions/runs')) return new Response('busy', { status: 503 });
    return githubFixture(url);
  } });
  const [first, same] = await Promise.all([feed(), feed()]);
  assert.equal(first, same);
  assert.equal(reads, 6);
  unavailable = true;
  time += 60_000;
  assert.equal((await feed()).projects[0].runs.state, 'current');
  time += 900_000;
  let [project] = (await feed()).projects;
  assert.equal(project.runs.state, 'stale');
  assert.equal(project.runs.observed, first.projects[0].runs.observed);
  assert.equal(project.runJobs[0].jobs.state, 'stale');
  assert.equal(project.issues.state, 'current');
  assert.equal(reads, 11);
  time += 24 * 60 * 60 * 1000;
  [project] = (await feed()).projects;
  assert.equal(project.runs.state, 'blocked');
  assert.equal(project.runs.data, null);
  assert.deepEqual(project.runJobs, []);
});

test('private auth or access failures invalidate previously observed results', async () => {
  let time = 0;
  let status;
  const feed = createFeed({ ...config([{ ...entry, visibility: 'private' }]), token, signal: signal(),
    now: () => time, fetcher: async (url) => status ? new Response('removed', { status }) : githubFixture(url) });
  assert.equal((await feed()).projects[0].runs.state, 'current');
  for (const [code, reason] of [[401, 'expired-or-invalid'], [403, 'inaccessible']]) {
    status = code;
    time += 300_000;
    const [project] = (await feed()).projects;
    assert.deepEqual(project.runs, { state: 'blocked', reason, observed: null, data: null });
    assert.equal(project.runJobs.length, 0);
  }
});

test('malformed content, rate limiting and transport failure remain distinct', async () => {
  for (const [response, reason] of [
    [() => Response.json({ workflow_runs: [{ ...run, id: '123/dispatch' }] }), 'malformed'],
    [() => new Response('invalid', { headers: { 'content-type': 'application/json' } }), 'malformed'],
    [() => Response.json({ oversized: 'x'.repeat(1_500_001) }), 'malformed'],
    [() => new Response('rate limited', { status: 403, headers: { 'x-ratelimit-remaining': '0' } }), 'rate-limit'],
    [() => { throw Error('private network details'); }, 'connection'],
  ]) {
    const feed = createFeed({ ...config(), signal: signal(), fetcher: async (url) =>
      url.includes('/actions/runs') ? response() : githubFixture(url) });
    const [project] = (await feed()).projects;
    assert.equal(project.runs.reason, reason);
    assert.equal(project.runs.state, 'blocked');
    assert.equal(project.issues.state, 'current');
  }
});

test('jobs reject mismatched identity, and proposals reject cross-repository source claims', async () => {
  const feed = createFeed({ ...config(), signal: signal(), fetcher: async (url) => {
    if (url.includes('/attempts/')) return Response.json({ total_count: 1, jobs: [{ ...job, run_attempt: 1 }] });
    if (url.includes('/contents/')) return Response.json(file({ ...plan,
      plan: { ...plan.plan, repository: 'someone/else' } }));
    return githubFixture(url);
  } });
  const [project] = (await feed()).projects;
  assert.equal(project.proposal.reason, 'malformed');
  assert.equal(project.runJobs[0].jobs.reason, 'malformed');
  assert.equal(project.runs.state, 'current');
});

test('Actions lifecycle and conclusion remain distinct', async () => {
  const observations = [
    { status: 'in_progress', conclusion: null }, { status: 'queued', conclusion: null },
    { status: 'waiting', conclusion: null }, { status: 'completed', conclusion: 'cancelled' },
  ];
  const feed = createFeed({ ...config(), signal: signal(), fetcher: async (url) => {
    if (url.includes('/attempts/')) return Response.json({ total_count: 0, jobs: [] });
    if (url.includes('/actions/runs')) return Response.json({
      workflow_runs: observations.map((status, index) => ({ ...run, ...status, id: run.id + index })),
    });
    return githubFixture(url);
  } });
  const [project] = (await feed()).projects;
  assert.deepEqual(project.runs.data.map((run) => [run.state, run.conclusion]), [
    ['running', null], ['queued', null], ['blocked', null], ['completed', 'cancelled'],
  ]);
});

test('service shutdown aborts reads and stops listening', async (t) => {
  let started;
  const readStarted = new Promise((resolve) => { started = resolve; });
  const app = missionControl(config(), { fetcher: async (_url, init) => {
    started();
    return new Promise((_, reject) => init.signal.addEventListener('abort', () => reject(Error('aborted')), { once: true }));
  } });
  t.after(() => app.stop());
  const origin = await listen(app);
  const request = fetch(`${origin}/api/mission-control`);
  await readStarted;
  await app.stop();
  assert.equal((await request).status, 200);
  await assert.rejects(fetch(`${origin}/healthz`), /fetch failed/);
});

test('invalid CLI configuration exits nonzero without printing secret paths', async () => {
  const proc = spawn(process.execPath, [fileURLToPath(new URL('../server.mjs', import.meta.url))], {
    env: { ...process.env, DAF_REPOSITORIES_FILE: 'unavailable-private-config.json' },
    stdio: ['ignore', 'ignore', 'pipe'],
  });
  let stderr = '';
  proc.stderr.setEncoding('utf8').on('data', (item) => { stderr += item; });
  const [code] = await once(proc, 'close');
  assert.equal(code, 1);
  assert.equal(stderr.trim(), 'Mission Control configuration could not be loaded');
});

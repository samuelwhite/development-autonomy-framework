import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { copyFile, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { bootstrapAccounts, openAccounts, username } from '../accounts.mjs';
import { loadConfig } from '../config.mjs';
import { missionControl } from '../server.mjs';
import { listen } from './fixtures.mjs';

const canonical = 'https://daf.example.test';
const admin = 'sample.admin';
const adminPassword = 'violet shelves reflect tomorrow';
const viewer = 'sample.viewer';
const viewerPassword = 'between oceans, winter changes colour';
const resetPassword = 'ridge paths are quiet before dawn';
const changedPassword = 'marble maps travel below the river';

async function storage(t, close) {
  const directory = await mkdtemp(join(tmpdir(), 'daf-accounts-'));
  t.after(async () => {
    await close?.();
    await rm(directory, { recursive: true, force: true });
  });
  return directory;
}

test('username validation accepts conventional names and bounded email identifiers', () => {
  const longest = `${'a'.repeat(64)}@${'b'.repeat(63)}.${'c'.repeat(63)}.${'d'.repeat(61)}`;
  assert.equal(longest.length, 254);
  assert.equal(username(longest), longest);
  assert.equal(username('Alice.Team+CI@Sub.Example-Test.org'), 'alice.team+ci@sub.example-test.org');
  assert.equal(username('Sample_User-1'), 'sample_user-1');
  assert.equal(username('a'.repeat(32)), 'a'.repeat(32));
  for (const invalid of [
    'a'.repeat(33), longest + 'd', `${'a'.repeat(65)}@example.test`,
    `a@${'b'.repeat(64)}.test`, 'a..b@example.test', '.a@example.test', 'a.@example.test',
    'a@-example.test', 'a@example-.test', 'a@example..test', 'a@example', 'a@@example.test',
    '@example.test', 'a@', ' a@example.test', 'a@example.test\n', 'a@exa_mple.test',
  ]) {
    assert.equal(username(invalid), null, invalid);
  }
});

test('email accounts bootstrap, deduplicate, restart and sign in case-insensitively', async (t) => {
  const directory = await storage(t);
  await assert.rejects(bootstrapAccounts(directory, 'invalid@@example.test', adminPassword), { status: 400 });
  await bootstrapAccounts(directory, 'Admin@Example.Test', adminPassword);
  const accounts = openAccounts(directory);
  try {
    const { id } = await accounts.login('ADMIN@example.test', adminPassword);
    await assert.rejects(accounts.add(id, 'aDmIn@eXample.Test', 'viewer', viewerPassword), { status: 409 });
    await assert.rejects(accounts.add(id, 'bad.@example.test', 'viewer', viewerPassword), { status: 400 });
    await assert.rejects(accounts.add(id, 'Alice.Team+CI@Example.Test', 'viewer', 'aliceteam1234'), { status: 400 });
    await accounts.add(id, 'Alice.Team+CI@Example.Test', 'viewer', viewerPassword);
  } finally {
    accounts.close();
  }
  const reopened = openAccounts(directory);
  try {
    const { id } = await reopened.login('ALICE.TEAM+Ci@example.TEST', viewerPassword);
    assert.equal(reopened.identity(id).name, 'alice.team+ci@example.test');
    await assert.rejects(reopened.login('alice.team+ci@@example.test', viewerPassword), { status: 401 });
  } finally {
    reopened.close();
  }
});

test('store fails closed, blocks common passwords and allows a long passphrase', async (t) => {
  const directory = await storage(t);
  assert.throws(() => openAccounts(directory), /ENOENT/);
  for (const password of ['short', '0123456789', 'sample.admin123', 'correct horse battery staple', 'iloveyou123']) {
    await assert.rejects(bootstrapAccounts(directory, admin, password), { status: 400 });
  }
  const longPassword = 'light over the hills keeps moving while the eastern sky turns blue';
  await bootstrapAccounts(directory, admin, longPassword);
  await assert.rejects(bootstrapAccounts(directory, 'second.admin', adminPassword), { code: 'EEXIST' });
  const stored = await readFile(join(directory, 'accounts.sqlite'));
  assert.ok(!stored.includes(longPassword));
  const accounts = openAccounts(directory);
  const { id } = await accounts.login('SAMPLE.ADMIN', longPassword);
  assert.ok(!((await readFile(join(directory, 'accounts.sqlite'))).includes(id)));
  await accounts.add(id, 'test.viewer', 'viewer', 'moss runes');
  assert.ok(await accounts.login('test.viewer', 'moss runes'));
  accounts.close();
  const restore = await storage(t);
  await copyFile(join(directory, 'accounts.sqlite'), join(restore, 'accounts.sqlite'));
  const restored = openAccounts(restore);
  try {
    assert.ok(restored.identity(id));
    restored.revokeAll();
    assert.equal(restored.identity(id), undefined);
    assert.ok(await restored.login(admin, longPassword));
  } finally {
    restored.close();
  }
  await writeFile(join(directory, 'accounts.sqlite'), 'corrupt');
  assert.throws(() => openAccounts(directory));
});

test('external accounts mode requires a canonical HTTPS origin and a bootstrapped store', async (t) => {
  const directory = await storage(t);
  const env = { DAF_AUTH_MODE: 'accounts', DAF_BIND: '0.0.0.0', DAF_AUTH_STATE_DIR: directory };
  for (const origin of [undefined, 'http://127.0.0.1:8080', 'https://example.test/login', 'https://user@example.test']) {
    assert.throws(() => loadConfig({ ...env, DAF_PUBLIC_ORIGIN: origin }), /HTTPS origin/);
  }
  const config = loadConfig({ ...env, DAF_PUBLIC_ORIGIN: canonical });
  assert.throws(() => missionControl(config), /ENOENT/);
  assert.throws(() => loadConfig({ DAF_AUTH_MODE: 'anonymous', DAF_BIND: '0.0.0.0' }), /authentication mode/);
});

test('interactive bootstrap rejects piped credentials', async () => {
  const proc = spawn(process.execPath, [fileURLToPath(new URL('../bootstrap.mjs', import.meta.url))],
    { stdio: ['pipe', 'pipe', 'pipe'] });
  let error = '';
  proc.stderr.setEncoding('utf8').on('data', (chunk) => { error += chunk; });
  proc.stdin.end('test-user\ntest-password\n');
  const [code] = await once(proc, 'close');
  assert.equal(code, 1);
  assert.match(error, /trusted interactive terminal/);
  assert.ok(!error.includes('test-password'));
});

test('account HTTP flow persists, enforces privileges, protects writes and revokes sessions', async (t) => {
  let app;
  const directory = await storage(t, () => app?.stop());
  await bootstrapAccounts(directory, admin, adminPassword);
  let now = Date.now();
  const settings = { repositories: [], authMode: 'accounts', publicOrigin: canonical, authDirectory: directory };
  app = missionControl(settings, { now: () => now });
  let origin = await listen(app);
  const paths = {
    login: '/api/account/login', logout: '/api/account/logout', password: '/api/account/password',
    create: '/api/users/create', reset: '/api/users/reset-password', status: '/api/users/status',
    users: '/api/users', feed: '/api/mission-control',
  };
  const get = (path, cookie) => fetch(origin + path, { redirect: 'manual', headers: cookie ? { cookie } : {} });
  const post = (path, data, cookie, requestOrigin = canonical) => fetch(origin + path, {
    method: 'POST', headers: { origin: requestOrigin, 'content-type': 'application/json', ...(cookie ? { cookie } : {}) },
    body: JSON.stringify(data),
  });
  async function login(username, password, prior) {
    const response = await post(paths.login, { username, password }, prior);
    assert.equal(response.status, 200);
    const cookie = response.headers.get('set-cookie');
    assert.match(cookie, /^__Host-daf_session=[a-f0-9]{64}; Path=\/; Max-Age=86400; Secure; HttpOnly; SameSite=Strict$/);
    return cookie.split(';')[0];
  }

  assert.equal((await get('/')).status, 303);
  assert.equal((await get('/login')).status, 200);
  assert.equal((await get(paths.feed)).status, 401);
  assert.equal((await get('/settings/users')).status, 303);
  assert.equal((await post(paths.feed, {})).status, 405);
  assert.equal((await post('/api/account/register', {})).status, 405);
  assert.equal((await fetch(origin + paths.login, {
    method: 'POST', headers: { origin: canonical, 'content-type': 'application/x-www-form-urlencoded' },
    body: 'username=sample.admin&password=dummy',
  })).status, 415);
  assert.equal((await post(paths.login, { username: admin, password: adminPassword }, null, 'https://other.test')).status, 403);
  const wrong = await post(paths.login, { username: admin, password: 'wrong' });
  const unknown = await post(paths.login, { username: 'unknown.user', password: 'wrong' });
  assert.equal(wrong.status, 401);
  assert.equal(unknown.status, 401);
  assert.deepEqual(await wrong.json(), await unknown.json());
  for (let attempt = 0; attempt < 4; attempt++) {
    assert.equal((await post(paths.login, { username: 'unknown.user', password: 'wrong' })).status, 401);
  }
  const limited = await post(paths.login, { username: 'unknown.user', password: 'wrong' });
  assert.equal(limited.status, 429);
  assert.equal(limited.headers.get('retry-after'), '300');
  const adminCookie = await login(admin, adminPassword);
  assert.equal((await get(paths.feed, `${adminCookie}; ${adminCookie}`)).status, 401);
  assert.equal((await get('/settings/users', adminCookie)).status, 200);
  assert.equal((await post(paths.create, { username: viewer, role: 'owner', password: viewerPassword }, adminCookie)).status, 400);
  assert.equal((await post(paths.create, { username: '<img>', role: 'viewer', password: viewerPassword }, adminCookie)).status, 400);
  assert.equal((await post(paths.create, { username: viewer, role: 'viewer', password: viewerPassword }, adminCookie, 'https://other.test')).status, 403);
  assert.equal((await post(paths.create, { username: viewer, role: 'viewer', password: viewerPassword }, adminCookie)).status, 200);
  assert.equal((await post(paths.create, { username: 'SAMPLE.VIEWER', role: 'viewer', password: viewerPassword }, adminCookie)).status, 409);
  const listed = await (await get(paths.users, adminCookie)).json();
  assert.deepEqual(listed, [{ username: admin, role: 'administrator', enabled: true },
    { username: viewer, role: 'viewer', enabled: true }]);
  assert.equal((await post(paths.status, { username: admin, enabled: false }, adminCookie)).status, 409);
  const oldViewer = await login(viewer, viewerPassword);
  const viewerCookie = await login(viewer, viewerPassword, oldViewer);
  assert.ok(oldViewer !== viewerCookie);
  assert.equal((await get(paths.feed, oldViewer)).status, 401);
  assert.equal((await get(paths.feed, viewerCookie)).status, 200);
  assert.equal((await get(paths.feed + '?repo=other/project', viewerCookie)).status, 404);
  assert.equal((await get('/settings/users', viewerCookie)).status, 403);
  assert.equal((await get(paths.users, viewerCookie)).status, 403);
  assert.equal((await post(paths.status, { username: admin, enabled: false }, viewerCookie)).status, 403);
  const change = await post(paths.password, { current: viewerPassword, password: changedPassword }, viewerCookie);
  assert.equal(change.status, 200);
  assert.match(change.headers.get('set-cookie'), /Max-Age=0/);
  assert.equal((await get(paths.feed, viewerCookie)).status, 401);
  const changed = await login(viewer, changedPassword);
  assert.equal((await post(paths.reset, { username: viewer, password: resetPassword }, adminCookie)).status, 200);
  assert.equal((await get(paths.feed, changed)).status, 401);
  const reset = await login(viewer, resetPassword);
  assert.equal((await post(paths.status, { username: viewer, enabled: false }, adminCookie)).status, 200);
  assert.equal((await get(paths.feed, reset)).status, 401);
  await app.stop();
  app = missionControl(settings, { now: () => now });
  origin = await listen(app);
  assert.equal((await get(paths.feed, adminCookie)).status, 200);
  assert.equal((await get(paths.feed, reset)).status, 401);
  assert.equal((await post(paths.login, { username: viewer, password: resetPassword })).status, 401);
  assert.equal((await post(paths.status, { username: viewer, enabled: true }, adminCookie)).status, 200);
  const reenabled = await login(viewer, resetPassword);
  assert.equal((await post(paths.logout, {}, reenabled)).status, 200);
  assert.equal((await get(paths.feed, reenabled)).status, 401);
  now += 86_400_000;
  assert.equal((await get(paths.feed, adminCookie)).status, 401);
});

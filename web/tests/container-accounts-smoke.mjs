import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { once } from 'node:events';

const origin = 'http://127.0.0.1:18080';
const compose = ['compose', '-f', 'compose.yaml', '-f', 'compose.accounts.yaml'];
const password = () => randomBytes(24).toString('hex');
const adminPassword = password();
const viewerPassword = password();

function docker(...args) {
  const result = spawnSync('docker', [...compose, ...args], { stdio: 'inherit', timeout: 60_000 });
  assert.equal(result.status, 0, 'Docker Compose command failed');
}

async function bootstrap() {
  const operator = spawn('script', ['--quiet', '--return', '--flush', '--command',
    'docker compose -f compose.yaml -f compose.accounts.yaml run --rm --no-deps mission-control node bootstrap.mjs',
    '/dev/null'], { stdio: ['pipe', 'pipe', 'pipe'] });
  const prompts = [
    ['Administrator username: ', 'ci.admin'],
    ['Administrator password: ', adminPassword],
    ['Repeat password: ', adminPassword],
  ];
  let transcript = '';
  let input = 0;
  let offset = 0;
  const expiry = setTimeout(() => operator.kill(), 30_000);
  operator.stdin.on('error', () => {});
  operator.stderr.resume();
  operator.stdout.setEncoding('utf8').on('data', (chunk) => {
    transcript += chunk;
    const prompt = prompts[input];
    const found = prompt ? transcript.indexOf(prompt[0], offset) : -1;
    if (found >= 0) {
      offset = found + prompt[0].length;
      input++;
      operator.stdin.write(prompt[1] + '\n');
    }
  });
  try {
    const [code] = await once(operator, 'close');
    assert.ok(!transcript.includes(adminPassword), 'Bootstrap must suppress password echo');
    assert.equal(input, prompts.length, 'Bootstrap did not present all interactive prompts');
    assert.equal(code, 0, 'Interactive first-administrator setup failed');
    assert.ok(transcript.includes('Administrator created.'));
  } finally {
    clearTimeout(expiry);
  }
}

function request(path, body, cookie) {
  return fetch(origin + path, {
    redirect: 'manual',
    headers: {
      Origin: process.env.DAF_PUBLIC_ORIGIN,
      ...(cookie ? { Cookie: cookie } : {}),
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    ...(body ? { method: 'POST', body: JSON.stringify(body) } : {}),
    signal: AbortSignal.timeout(5_000),
  });
}

async function login(username, password) {
  const response = await request('/api/account/login', { username, password });
  assert.equal(response.status, 200);
  const cookie = response.headers.get('set-cookie');
  assert.ok(cookie && cookie.endsWith('Secure; HttpOnly; SameSite=Strict'));
  return cookie.split(';')[0];
}

await bootstrap();
docker('up', '--no-build', '--wait', '--wait-timeout', '35');
docker('exec', '-T', 'mission-control', 'test', '-w', '/var/lib/daf-auth');
docker('exec', '-T', 'mission-control', 'test', '!', '-e', '/run/secrets/viewer_password');
assert.equal((await request('/healthz')).status, 200);
assert.equal((await request('/')).status, 303);
assert.equal((await request('/api/mission-control')).status, 401);
const administrator = await login('ci.admin', adminPassword);
assert.equal((await request('/api/users/create',
  { username: 'ci.viewer', role: 'viewer', password: viewerPassword }, administrator)).status, 200);
const invalidated = await login('ci.viewer', viewerPassword);
assert.equal((await request('/api/account/logout', {}, invalidated)).status, 200);
docker('restart');
docker('up', '--no-build', '--no-recreate', '--wait', '--wait-timeout', '35');
assert.equal((await request('/api/users', null, administrator)).status, 200);
assert.equal((await request('/api/account', null, invalidated)).status, 401);
const viewer = await login('ci.viewer', viewerPassword);
assert.equal((await request('/api/users', null, viewer)).status, 403);
const rollback = spawnSync('docker', ['compose', '-f', 'compose.yaml', 'up', '--no-build',
  '--wait', '--wait-timeout', '35'], { stdio: 'inherit', timeout: 60_000 });
assert.equal(rollback.status, 0, 'Basic Auth rollback failed');
const rolledBack = await request('/', null, administrator);
assert.equal(rolledBack.status, 401);
assert.match(rolledBack.headers.get('www-authenticate'), /^Basic /);
console.log('Interactive bootstrap, permissions, restart persistence and Basic Auth rollback passed.');

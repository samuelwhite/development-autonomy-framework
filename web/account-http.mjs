import { AccountError, openAccounts, username } from './accounts.mjs';

const cookieName = '__Host-daf_session';
const cookie = (value, age) =>
  `${cookieName}=${value}; Path=/; Max-Age=${age}; Secure; HttpOnly; SameSite=Strict`;
const jsonType = 'application/json; charset=utf-8';
const maxBody = 4096;
const windowSeconds = 300;

function sessionId(request) {
  const pairs = (request.headers.cookie || '').split(';').map((part) => part.trim())
    .filter((part) => part.startsWith(`${cookieName}=`));
  return pairs.length === 1 ? pairs[0].slice(cookieName.length + 1) : '';
}

async function payload(request, keys) {
  if (!/^application\/json(?:;\s*charset=utf-8)?$/i.test(request.headers['content-type'] || '')) {
    throw new AccountError(415, 'Send a JSON request.');
  }
  if (Number(request.headers['content-length']) > maxBody) throw new AccountError(413, 'Request is too large.');
  let length = 0;
  const chunks = [];
  for await (const chunk of request.iterator({ destroyOnReturn: false })) {
    length += chunk.length;
    if (length > maxBody) {
      request.resume();
      throw new AccountError(413, 'Request is too large.');
    }
    chunks.push(chunk);
  }
  let data;
  try {
    data = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks)));
  } catch {
    throw new AccountError(400, 'Invalid request.');
  }
  if (!data || typeof data !== 'object' || Array.isArray(data) ||
      Object.keys(data).length !== keys.length || !keys.every((key) => Object.hasOwn(data, key))) {
    throw new AccountError(400, 'Invalid request.');
  }
  return data;
}

function rateLimiter(now) {
  const attempts = new Map();
  let windowEnd = 0;
  let total = 0;
  return (key) => {
    if (now() >= windowEnd) {
      attempts.clear();
      total = 0;
      windowEnd = now() + windowSeconds * 1000;
    }
    const count = attempts.get(key) || 0;
    if (count >= 5 || total >= 40) throw new AccountError(429, 'Too many requests. Try again in a few minutes.');
    attempts.set(key, count + 1);
    total++;
  };
}

export function accountHttp(config, now = Date.now) {
  const accounts = openAccounts(config.authDirectory, now);
  const limit = rateLimiter(now);
  const routes = new Map([
    ['/api/account/login', { keys: ['username', 'password'], run: async (id, data) => {
      limit(`login:${username(data.username) ?? ''}`);
      const result = await accounts.login(data.username, data.password, id);
      return { 'Set-Cookie': cookie(result.id, result.maxAge) };
    } }],
    ['/api/account/logout', { keys: [], run: (id) => {
      accounts.logout(id);
      return { 'Set-Cookie': cookie('', 0) };
    } }],
    ['/api/account/password', { keys: ['current', 'password'], run: async (id, data, user) => {
      limit(`password:${user.name}`);
      await accounts.change(id, data.current, data.password);
      return { 'Set-Cookie': cookie('', 0) };
    } }],
    ['/api/users/create', { admin: true, keys: ['username', 'role', 'password'],
      run: (id, data) => accounts.add(id, data.username, data.role, data.password) }],
    ['/api/users/reset-password', { admin: true, keys: ['username', 'password'],
      run: (id, data) => accounts.reset(id, data.username, data.password) }],
    ['/api/users/status', { admin: true, keys: ['username', 'enabled'],
      run: (id, data) => accounts.status(id, data.username, data.enabled) }],
  ]);
  return {
    close: accounts.close,
    identity: (request) => accounts.identity(sessionId(request)),
    async handle(request, send) {
      const path = request.url;
      const post = request.method === 'POST' && routes.get(path);
      const read = ['GET', 'HEAD'].includes(request.method) && ['/api/account', '/api/users'].includes(path);
      if (!post && !read) return false;
      const json = (status, data, headers) => send(status, jsonType, JSON.stringify(data), headers);
      try {
        if (post && request.headers.origin !== config.publicOrigin) {
          throw new AccountError(403, 'Request origin is not allowed.');
        }
        const id = sessionId(request);
        const user = accounts.identity(id);
        if (path !== '/api/account/login' && path !== '/api/account/logout' && !user) {
          throw new AccountError(401, 'Sign in to continue.');
        }
        if ((post?.admin || path === '/api/users') && user?.role !== 'administrator') {
          throw new AccountError(403, 'Administrator access is required.');
        }
        if (post) {
          const headers = await post.run(id, await payload(request, post.keys), user);
          json(200, { ok: true }, headers);
        } else {
          json(200, path === '/api/users' ? accounts.list(id) : { username: user.name, role: user.role });
        }
      } catch (error) {
        if (error instanceof AccountError) {
          json(error.status, { error: error.message }, error.status === 429 ? { 'Retry-After': String(windowSeconds) } : {});
        } else {
          json(503, { error: 'Account service is unavailable.' });
        }
      }
      return true;
    },
  };
}

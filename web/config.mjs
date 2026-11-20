import { readFileSync } from 'node:fs';

export const PUBLIC_DAF = 'samuelwhite/development-autonomy-framework';
export const SHA = /^[a-f0-9]{40}$/;
const REPO = /^[a-z\d][a-z\d-]{0,38}\/[a-z\d_.-]{1,100}$/i;
const PLAN_PATH = /^(?:[a-z\d_-][a-z\d_.-]*\/)*[a-z\d_-][a-z\d_.-]*\.json$/i;

const defaults = [{
  repository: PUBLIC_DAF,
  visibility: 'public',
  planning: true,
  plan: {
    commit: 'c331e26d83432540f397f28b307d529d9a215c1d',
    path: 'docs/plans/m1.2-readiness.json',
  },
}];

export function validateRepositories(entries) {
  if (!Array.isArray(entries) || entries.length > 8) throw Error('Invalid repository list');
  const seen = new Set();
  return entries.map((entry) => {
    if (!entry || typeof entry.repository !== 'string' || !REPO.test(entry.repository) ||
        /\/\.{1,2}$/.test(entry.repository) || !['public', 'private'].includes(entry.visibility) ||
        (entry.planning !== undefined && typeof entry.planning !== 'boolean')) {
      throw Error('Invalid repository entry');
    }
    const repository = entry.repository.toLowerCase();
    if (seen.has(repository)) throw Error('Duplicate repository entry');
    seen.add(repository);
    const plan = entry.plan;
    if (plan !== undefined && (!entry.planning || !plan || typeof plan.commit !== 'string' ||
        !SHA.test(plan.commit) || typeof plan.path !== 'string' || plan.path.length > 240 ||
        !PLAN_PATH.test(plan.path))) throw Error('Invalid pinned proposal');
    return {
      repository, visibility: entry.visibility, planning: entry.planning === true,
      plan: plan && { commit: plan.commit, path: plan.path },
    };
  });
}

function readSecret(path) {
  return path ? readFileSync(path, 'utf8').trim() : '';
}

export function loadConfig(env = process.env) {
  const repositories = validateRepositories(env.DAF_REPOSITORIES_FILE
    ? JSON.parse(readFileSync(env.DAF_REPOSITORIES_FILE, 'utf8')) : defaults);
  const token = readSecret(env.DAF_GITHUB_TOKEN_FILE);
  const password = readSecret(env.DAF_VIEWER_PASSWORD_FILE);
  if ((password && !/^[!-~]{24,256}$/.test(password)) ||
      (env.DAF_VIEWER_PASSWORD_FILE && !password) ||
      (token && !/^[A-Za-z0-9_]{1,512}$/.test(token))) throw Error('Invalid secret configuration');
  if (repositories.some((entry) => entry.visibility === 'private') && !password) {
    throw Error('Private sources require viewer authentication');
  }
  const host = env.DAF_BIND || '127.0.0.1';
  const port = Number(env.DAF_PORT || 8080);
  if (!['127.0.0.1', '0.0.0.0'].includes(host) || !Number.isInteger(port) || port < 1 || port > 65535) {
    throw Error('Invalid listener configuration');
  }
  return { repositories, token, password, host, port };
}

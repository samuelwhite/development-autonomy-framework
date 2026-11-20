import { sources } from './github.mjs';

const MINUTE = 60 * 1_000;
const DISCARD_MS = 24 * 60 * 60 * 1_000;
const errors = new Set(['malformed', 'connection', 'rate-limit', 'expired-or-invalid',
  'inaccessible', 'upstream']);
const absent = (reason) => ({ state: 'unconfigured', reason, observed: null, data: null });

export function createFeed({ repositories, token, signal, fetcher = fetch, now = Date.now }) {
  // At most nine GETs per refresh per public repository. Leave room in GitHub's
  // anonymous 60/hour budget for other traffic from the same IP.
  const publicSources = repositories.filter((entry) => entry.visibility === 'public').length;
  const refreshMs = Math.max(5, 15 * publicSources) * MINUTE;
  const cache = new Map();
  let nextRead = 0;
  let inFlight;
  let snapshot;

  async function refresh() {
    const used = new Set();
    async function observe(key, read, missing = 'not-configured') {
      if (!read) return absent(missing);
      used.add(key);
      try {
        const data = await read();
        const observed = new Date(now()).toISOString();
        cache.set(key, { data, observed });
        return { state: 'current', reason: null, observed, data };
      } catch (error) {
        const reason = errors.has(error.code) ? error.code : 'upstream';
        const previous = cache.get(key);
        if (previous && !['expired-or-invalid', 'inaccessible'].includes(reason) &&
            now() - Date.parse(previous.observed) < DISCARD_MS) {
          return { state: 'stale', reason, ...previous };
        }
        cache.delete(key);
        return { state: 'blocked', reason, observed: null, data: null };
      }
    }

    const projects = await Promise.all(repositories.map(async (config) => {
      const { repository, visibility, planning } = config;
      const credentialsMissing = visibility === 'private' && !token;
      const reader = credentialsMissing ? {} : sources(config, visibility === 'private' ? token : '', fetcher, signal);
      const read = (key) => observe(`${repository}:${key}`, reader[key],
        credentialsMissing ? 'missing-credential' : 'not-configured');
      const [milestones, issues, pulls, proposal, runs] = await Promise.all(
        ['milestones', 'issues', 'pulls', 'proposal', 'runs'].map(read));
      const runJobs = await Promise.all((runs.data ?? []).map(async (run) => {
        const key = `${repository}:jobs:${run.id}:${run.attempt}:${run.commit}`;
        // A failed run refresh must not make job reads appear to validate that stale run.
        if (runs.state === 'stale') {
          used.add(key);
          const previous = cache.get(key);
          return { runId: run.id, attempt: run.attempt, jobs: previous &&
            now() - Date.parse(previous.observed) < DISCARD_MS
            ? { state: 'stale', reason: runs.reason, ...previous }
            : { state: 'blocked', reason: runs.reason, observed: null, data: null } };
        }
        return { runId: run.id, attempt: run.attempt, jobs: await observe(key, reader.jobs(run)) };
      }));
      return { repository, visibility, planning, milestones, issues, pulls, proposal, runs, runJobs };
    }));
    for (const key of cache.keys()) if (!used.has(key)) cache.delete(key);
    return { projects, reviewedAt: new Date(now()).toISOString(), staleAfterMs: refreshMs * 2 };
  }

  return async () => {
    if (!inFlight && (!snapshot || now() >= nextRead)) {
      inFlight = refresh().then((value) => {
        snapshot = value;
        nextRead = now() + refreshMs;
        return value;
      }).finally(() => { inFlight = undefined; });
    }
    return inFlight || snapshot;
  };
}

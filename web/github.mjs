import { SHA } from './config.mjs';

const API = 'https://api.github.com';
const PAGE = 12;
const RUNS = 4;
const JOBS = 20;
const MAX_BYTES = 1_500_000;
const object = (value) => value && typeof value === 'object' && !Array.isArray(value);
const positive = (value) => Number.isSafeInteger(value) && value > 0;
const count = (value) => Number.isSafeInteger(value) && value >= 0;
const validSha = (value) => typeof value === 'string' && SHA.test(value);
const closedOrOpen = (value) => value === 'open' || value === 'closed';

class SourceError extends Error {
  constructor(code) { super(code); this.code = code; }
}

function check(condition) {
  if (!condition) throw new SourceError('malformed');
}

function text(value, limit = 300) {
  check(typeof value === 'string' && value.trim());
  return value.slice(0, limit);
}

function date(value) {
  check(typeof value === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(value) &&
    Number.isFinite(Date.parse(value)));
  return value;
}

function page(value, limit) {
  check(Array.isArray(value) && value.length <= limit && value.every(object));
  return value;
}

async function boundedJson(response) {
  check(response.body && /^(application\/json|application\/vnd\.github\+json)\b/i.test(
    response.headers.get('content-type') || ''));
  const chunks = [];
  let bytes = 0;
  for await (const chunk of response.body) {
    bytes += chunk.length;
    check(bytes <= MAX_BYTES);
    chunks.push(chunk);
  }
  try {
    return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks)));
  } catch {
    throw new SourceError('malformed');
  }
}

async function read(fetcher, repository, path, token, signal) {
  const headers = { Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' };
  if (token) headers.Authorization = `Bearer ${token}`;
  let response;
  try {
    response = await fetcher(`${API}/repos/${repository}${path}`, {
      method: 'GET', redirect: 'error', headers,
      signal: AbortSignal.any([signal, AbortSignal.timeout(7_000)]),
    });
    if (response.ok) return await boundedJson(response);
  } catch (error) {
    if (response?.body && !response.body.locked) await response.body.cancel().catch(() => {});
    if (error instanceof SourceError) throw error;
    throw new SourceError('connection');
  }
  await response.body?.cancel().catch(() => {});
  if (response.status === 429 || (response.status === 403 &&
      (response.headers.get('x-ratelimit-remaining') === '0' || response.headers.has('retry-after')))) {
    throw new SourceError('rate-limit');
  }
  if (response.status === 401) throw new SourceError('expired-or-invalid');
  if ([403, 404, 451].includes(response.status)) throw new SourceError('inaccessible');
  throw new SourceError('upstream');
}

function milestones(value, base) {
  return page(value, PAGE).map((m) => {
    check(positive(m.number) && closedOrOpen(m.state) && count(m.open_issues) && count(m.closed_issues));
    return {
      title: text(m.title), state: m.state, open: m.open_issues, closed: m.closed_issues,
      updated: date(m.updated_at), url: `${base}/milestone/${m.number}`,
    };
  });
}

function issues(value, base) {
  return page(value, PAGE).filter((issue) => !issue.pull_request).map((issue) => {
    check(positive(issue.number) && closedOrOpen(issue.state) && Array.isArray(issue.labels));
    return {
      number: issue.number, title: text(issue.title), state: issue.state,
      reason: ['completed', 'not_planned', 'duplicate', 'reopened'].includes(issue.state_reason)
        ? issue.state_reason : null,
      labels: issue.labels.slice(0, 25).map((label) => text(label?.name, 80)),
      updated: date(issue.updated_at), url: `${base}/issues/${issue.number}`,
    };
  });
}

function pulls(value, base) {
  return page(value, PAGE).map((pr) => {
    check(positive(pr.number) && closedOrOpen(pr.state) && validSha(pr.head?.sha) &&
      typeof pr.draft === 'boolean' && (pr.merged_at === null || pr.state === 'closed'));
    return {
      number: pr.number, title: text(pr.title), state: pr.merged_at ? 'merged' : pr.state,
      draft: pr.state === 'open' && pr.draft, updated: date(pr.updated_at),
      mergeDate: pr.merged_at === null ? null : date(pr.merged_at),
      commit: pr.head.sha, commitUrl: `${base}/pull/${pr.number}/commits/${pr.head.sha}`,
      url: `${base}/pull/${pr.number}`,
    };
  });
}

function outcome(item) {
  const status = text(item.status, 40);
  const conclusion = item.conclusion === null ? null : text(item.conclusion, 40);
  if (status === 'completed') {
    if (['failure', 'timed_out', 'startup_failure', 'action_required', 'stale'].includes(conclusion)) {
      return { status, conclusion, state: 'failed' };
    }
    if (['success', 'neutral', 'skipped', 'cancelled'].includes(conclusion)) {
      return { status, conclusion, state: 'completed' };
    }
  }
  const states = { in_progress: 'running', queued: 'queued', requested: 'queued',
    pending: 'queued', waiting: 'blocked' };
  return { status, conclusion, state: Object.hasOwn(states, status) ? states[status] : 'unknown' };
}

function runs(value, base) {
  return page(value?.workflow_runs, RUNS).map((run) => {
    check(positive(run.id) && positive(run.run_attempt) && positive(run.workflow_id) && validSha(run.head_sha));
    const url = `${base}/actions/runs/${run.id}/attempts/${run.run_attempt}`;
    const workflow = typeof run.path === 'string' &&
      /^\.github\/workflows\/([a-zA-Z0-9_.-]+\.ya?ml)$/.exec(run.path);
    return {
      id: run.id, attempt: run.run_attempt, title: text(run.name), ...outcome(run),
      updated: date(run.updated_at), commit: run.head_sha, branch: run.head_branch == null
        ? null : text(run.head_branch, 160),
      commitUrl: `${base}/commit/${run.head_sha}`, url, artifactsUrl: `${url}#artifacts`,
      workflowUrl: workflow ? `${base}/actions/workflows/${workflow[1]}` : null,
    };
  });
}

function jobs(value, base, run) {
  check(count(value?.total_count));
  const items = page(value.jobs, JOBS).map((job) => {
    check(positive(job.id) && job.run_id === run.id && job.run_attempt === run.attempt &&
      job.head_sha === run.commit && Array.isArray(job.labels));
    return {
      id: job.id, title: text(job.name), ...outcome(job),
      started: job.started_at === null ? null : date(job.started_at),
      completed: job.completed_at === null ? null : date(job.completed_at),
      runner: job.runner_name == null || job.runner_name === '' ? null : text(job.runner_name, 160),
      runnerId: positive(job.runner_id) ? job.runner_id : null,
      selfHosted: job.labels.includes('self-hosted'), url: `${base}/actions/runs/${run.id}/job/${job.id}`,
    };
  });
  return { items, total: value.total_count };
}

function proposal(value, config, base) {
  check(value?.type === 'file' && value.path === config.plan.path && value.encoding === 'base64' &&
    typeof value.content === 'string' && value.content.length <= 160_000 && validSha(value.sha));
  let document;
  try {
    const encoded = value.content.replaceAll('\n', '');
    check(/^[A-Za-z0-9+/]+={0,2}$/.test(encoded));
    const bytes = Buffer.from(encoded, 'base64');
    check(bytes.toString('base64') === encoded);
    document = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
  } catch {
    throw new SourceError('malformed');
  }
  const plan = document?.plan;
  check(document?.schema_version === 1 && plan?.schema_version === 1 &&
    typeof plan.repository === 'string' && plan.repository.toLowerCase() === config.repository &&
    validSha(plan.baseline_revision));
  const tasks = page(document.tasks, 50);
  const milestones = page(plan.milestones, 50);
  check(tasks.length > 0 && tasks.length === milestones.length);
  const byId = new Map(milestones.map((m) => [text(m.id, 80), text(m.deliverable)]));
  check(byId.size === milestones.length);
  const proposals = tasks.map((task) => {
    const id = text(task.milestone_id, 80);
    check(byId.has(id));
    const title = byId.get(id);
    byId.delete(id);
    return { id, title, instruction: text(task.instruction, 650) };
  });
  return {
    title: text(plan.plan_id, 120), commit: config.plan.commit, baseline: plan.baseline_revision,
    url: `${base}/blob/${config.plan.commit}/${config.plan.path}`,
    baselineUrl: `${base}/commit/${plan.baseline_revision}`, tasks: proposals,
  };
}

export function sources(config, token, fetcher, signal) {
  const base = `https://github.com/${config.repository}`;
  const get = (path) => read(fetcher, config.repository, path, token, signal);
  const listing = `state=all&per_page=${PAGE}`;
  return {
    milestones: config.planning && (async () => milestones(await get(`/milestones?${listing}`), base)),
    issues: config.planning && (async () => issues(await get(`/issues?${listing}&sort=updated&direction=desc`), base)),
    pulls: config.planning && (async () => pulls(await get(`/pulls?${listing}&sort=updated&direction=desc`), base)),
    proposal: config.plan && (async () => proposal(
      await get(`/contents/${config.plan.path}?ref=${config.plan.commit}`), config, base)),
    runs: async () => runs(await get(`/actions/runs?per_page=${RUNS}`), base),
    jobs: (run) => async () => jobs(await get(
      `/actions/runs/${run.id}/attempts/${run.attempt}/jobs?per_page=${JOBS}`), base, run),
  };
}

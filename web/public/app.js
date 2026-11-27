'use strict';

const views = {
  dashboard: ['Dashboard', 'Project planning, validation activity and work that needs a closer look.'],
  development: ['Development', 'GitHub planning, pinned proposals and pull request review.'],
  homeci: ['HomeCI', 'Workflow results, job logs and runner observations from GitHub Actions.'],
};
const labels = {
  current: 'Current', stale: 'Stale', blocked: 'Blocked', unconfigured: 'Unconfigured',
  running: 'Running', completed: 'Completed', failed: 'Failed', queued: 'Queued', unknown: 'Unknown',
  open: 'Open', closed: 'Closed', merged: 'Merged', draft: 'Draft', proposed: 'Proposed',
};
const problems = {
  'missing-credential': 'Ask the operator to configure read-only GitHub access.',
  'expired-or-invalid': 'Ask the operator to renew or replace the GitHub credential.',
  inaccessible: 'Ask the operator to check repository access or feature availability.',
  'rate-limit': 'GitHub is limiting requests. The feed will retry on its next update.',
  malformed: 'GitHub returned unexpected data. Open the source to check it directly.',
  connection: 'Mission Control could not reach GitHub.',
  upstream: 'GitHub did not provide a usable response.',
  'not-configured': 'This source has not been configured.',
};
const byId = (id) => document.getElementById(id);
const content = byId('view');
const connection = byId('connection');
const button = byId('refresh');
const formatTime = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC',
});
const timestamp = (value) => `${formatTime.format(new Date(value))} UTC`;
const latest = (items) => items.sort((a, b) => b.updated.localeCompare(a.updated));
let snapshot;
let connectionError;
let loading = false;
let active = 'dashboard';

function element(tag, className, ...children) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.append(...children.filter((child) => child != null && child !== false));
  return node;
}

function link(label, url) {
  const node = element('a', '', label);
  if (url.startsWith('#')) {
    node.href = url;
    return node;
  }
  const address = new URL(url);
  if (address.origin === 'https://github.com' && !address.username && !address.password) {
    node.href = address.href;
    node.rel = 'noreferrer';
    return node;
  }
  return element('span', '', label);
}

function badge(state, label = labels[state]) {
  const node = element('span', 'badge', label);
  node.dataset.state = state;
  return node;
}

function panel(title, children, more) {
  return element('section', 'panel', element('div', 'panel-head', element('h2', '', title), more), ...children);
}

const note = (sentence) => element('p', 'note', sentence);
const row = (title, status, ...rest) => element('li', '', element('div', 'row', title, status), ...rest);
const list = (items) => element('ul', 'list', ...items);
const meta = (...parts) => element('p', 'meta', parts.filter(Boolean).join(' · '));
const links = (...items) => element('div', 'links', ...items);
const short = (repo) => repo.split('/')[1];
const repoUrl = (repo) => `https://github.com/${repo}`;

function freshness(feed) {
  if (feed.state === 'current' && (connectionError ||
      Date.now() - Date.parse(feed.observed) > snapshot.staleAfterMs)) return 'stale';
  return feed.state;
}

function sourceNote(feed) {
  const state = freshness(feed);
  const message = problems[feed.reason] || (state === 'stale' ? 'Refresh to check for updates.' : '');
  return element('div', '',
    element('div', 'runner-health', badge(state), feed.observed && meta(`Observed ${timestamp(feed.observed)}`)),
    message && note(message));
}

function sourceRows(feed, renderRows, empty) {
  const rows = feed.data && renderRows(feed.data);
  return [sourceNote(feed), rows?.length ? list(rows) : feed.data != null ? note(empty) : null];
}

function pullRow(pr, repo) {
  return row(link(`#${pr.number} ${pr.title}`, pr.url), badge(pr.draft ? 'draft' : pr.state),
    meta(repo && short(repo), `${pr.mergeDate ? 'Merged' : 'Updated'} ${timestamp(pr.mergeDate || pr.updated)}`),
    links(link(`Head ${pr.commit.slice(0, 8)}`, pr.commitUrl)));
}

function issueRow(issue, repo) {
  return row(link(`#${issue.number} ${issue.title}`, issue.url), badge(issue.state),
    meta(repo && short(repo), issue.reason?.replaceAll('_', ' '), ...issue.labels,
      `Updated ${timestamp(issue.updated)}`));
}

function runBadge(run) {
  const status = run.conclusion?.replaceAll('_', ' ');
  return badge(run.state, status ? `${labels[run.state]} · ${status}` : labels[run.state]);
}

function runRow(run, repo, feed, details, candidate) {
  return row(link(run.title, run.url), runBadge(run),
    meta(short(repo), run.branch, details ? null : `Attempt ${run.attempt}`, timestamp(run.updated)),
    details && element('p', 'meta', element('code', '', `Run ${run.id} · Attempt ${run.attempt}`)),
    links(run.workflowUrl && link('Workflow', run.workflowUrl),
      link(element('span', '', 'Commit ', element('code', '', details ? run.commit : run.commit.slice(0, 8))),
        run.commitUrl), !run.candidate && link('Artifacts', run.artifactsUrl)),
    freshness(feed) === 'stale' && meta(`Stale result · observed ${timestamp(feed.observed)}`), candidate, details);
}

function dashboard(projects) {
  const entries = projects.flatMap((project) => (project.runs.data ?? []).map((run) =>
    ({ ...run, repository: project.repository, feed: project.runs })));
  const newestByWorkflow = new Map();
  for (const run of latest(entries)) {
    const key = `${run.repository}:${run.workflowUrl || run.title}:${run.branch}`;
    if (!newestByWorkflow.has(key)) newestByWorkflow.set(key, run);
  }
  const checks = [...newestByWorkflow.values()].filter((run) => ['failed', 'blocked'].includes(run.state));
  const attention = checks.slice(0, 5).map((run) => runRow(run, run.repository, run.feed));
  for (const project of projects) {
    for (const [label, feed] of [['Milestones', project.milestones], ['Issues', project.issues],
      ['Pull requests', project.pulls], ['Pinned proposals', project.proposal], ['Actions', project.runs]]) {
      const state = freshness(feed);
      if (['blocked', 'stale'].includes(state) || feed.reason === 'missing-credential') {
        attention.push(row(link(`${short(project.repository)} · ${label}`,
          label === 'Actions' ? '#homeci' : '#development'), badge(state),
        meta(problems[feed.reason] || 'Refresh to check for updates.')));
      }
    }
  }
  for (const project of projects.filter((item) => freshness(item.runs) === 'current')) {
    const affected = project.runJobs.filter(({ jobs }) => freshness(jobs) !== 'current');
    if (affected.length) {
      attention.push(row(link(`${short(project.repository)} · Job observations`, '#homeci'),
        badge(affected.some(({ jobs }) => freshness(jobs) === 'blocked') ? 'blocked' : 'stale'),
        meta(`${affected.length} workflow attempts have incomplete job observations`)));
    }
  }
  const issues = latest(projects.flatMap((project) => (project.issues.data ?? [])
    .filter((issue) => issue.state === 'open').map((issue) => ({ ...issue, repo: project.repository,
      stale: freshness(project.issues) === 'stale' }))));
  // A GitHub label is a source claim about a decision, never an approval in DAF.
  const decision = (issue) => issue.labels.some((label) => /^(product[ -]decision|decision[ -]required)$/i.test(label));
  const decisions = issues.filter(decision).slice(0, 5);
  const openWork = issues.filter((issue) => !decision(issue)).slice(0, 4);
  const planningAvailable = projects.some((project) => freshness(project.issues) === 'current');
  const issueWithFreshness = (issue) => {
    const item = issueRow(issue, issue.repo);
    if (issue.stale) item.append(meta('Stale issue observation'));
    return item;
  };
  const prs = latest(projects.flatMap((project) => (project.pulls.data ?? []).map((pr) =>
    ({ ...pr, repo: project.repository, stale: freshness(project.pulls) === 'stale' }))));
  const projectRows = projects.map((project) => {
    const milestones = project.milestones;
    const planning = milestones.data
      ? `${milestones.data.filter((item) => item.state === 'open').length} open milestones in recent results`
      : `Milestones ${labels[freshness(milestones)].toLowerCase()}`;
    const proposal = project.proposal.data?.tasks.length;
    return row(link(short(project.repository), repoUrl(project.repository)), badge(freshness(project.runs)),
      meta(planning, proposal && `${proposal} pinned proposals`, `${project.visibility} GitHub repository`),
      project.runs.observed && meta(`Actions observed ${timestamp(project.runs.observed)}`));
  });
  return element('div', 'dashboard',
    element('div', 'stack',
      panel('Projects', [list(projectRows)], link('View development', '#development')),
      panel('Needs attention', [attention.length ? list(attention) : note('No failures or feed issues in the latest observations.')]),
      panel('Product decisions', [decisions.length ? list(decisions.map(issueWithFreshness)) :
        note(planningAvailable ? 'No open issues labelled as Product decisions in the current planning window.' :
          'Current GitHub issues are unavailable.')]),
      panel('Open work', [openWork.length ? list(openWork.map(issueWithFreshness)) : note('No open issues in the available planning window.')])),
    element('div', 'stack',
      panel('Latest validation', [entries.length ? list(entries.slice(0, 4).map((run) =>
        runRow(run, run.repository, run.feed))) : note('No workflow runs available.')], link('View HomeCI', '#homeci')),
      panel('Recent pull requests', [prs.length ? list(prs.slice(0, 4).map((pr) => {
        const item = pullRow(pr, pr.repo);
        if (pr.stale) item.append(meta('Stale pull request observation'));
        return item;
      })) : note('No pull requests in the available window.')])));
}

function projectSection(project, ...sections) {
  return element('section', 'project', element('div', 'row',
    element('h2', '', link(short(project.repository), repoUrl(project.repository))), badge('', project.visibility)),
  ...sections);
}

// Summaries of published planning documents at the UI-01 base, not live milestone status.
const roadmapSource = 'https://github.com/samuelwhite/development-autonomy-framework/blob/c331e26d83432540f397f28b307d529d9a215c1d/docs/';
const roadmap = [
  ['M1', 'Integration and read-only desktop planning', 'Review evidence', '',
    'M1.2 imports commit-pinned public plans and reopens validated snapshots. Its Windows candidate remains subject to separate Product review.',
    'M1.2 review evidence', 'm1.2-validation.md'],
  ['M2', 'Supervised local execution proposal', 'Execution gated', 'blocked',
    'M2.1A is a candidate for Product acceptance. Its validation does not authorise M2.1B or desktop execution.',
    'M2.1 proposal and review gate', 'm2.1-supervised-execution-proposal.md#stop-and-review-gate'],
  ['M3', 'Future execution scope', 'Status unknown', 'unknown',
    'The M2.1 proposal excludes M3 from its approval exceptions. This source does not define an M3 delivery plan or approval.',
    'M2.1 scope exclusions', 'm2.1-supervised-execution-proposal.md#stop-and-review-gate'],
];

function development(projects) {
  return element('div', 'stack', note('Proposals describe intended work. Pull request and CI outcomes record activity at their sources.'),
    panel('DAF roadmap', [
      note('Planning summaries from a pinned source revision. Execution approval is recorded separately.'),
      list(roadmap.map(([id, title, label, state, summary, source, path]) => row(
        element('h3', '', element('code', '', id), ` · ${title}`), badge(state, label),
        element('p', 'detail', summary), links(link(source, roadmapSource + path))))),
    ]),
    ...projects.map((project) => projectSection(project,
      element('div', 'project-grid',
        panel('Milestones', sourceRows(project.milestones, (items) => items.map((item) =>
          row(link(item.title, item.url), badge(item.state), meta(`${item.open} open · ${item.closed} closed`,
            `Updated ${timestamp(item.updated)}`))), 'No GitHub milestones returned.')),
        panel('Pinned proposals', [sourceNote(project.proposal), project.proposal.data && (() => {
          const plan = project.proposal.data;
          return element('div', '', links(link('Plan source', plan.url),
            link(`Baseline ${plan.baseline.slice(0, 8)}`, plan.baselineUrl)),
          list(plan.tasks.map((task) => row(element('h3', '', task.title), badge('proposed'),
            meta(task.id), element('p', 'detail', task.instruction)))));
        })()]),
        panel('GitHub issues', sourceRows(project.issues, (items) => items.map((issue) => issueRow(issue)), 'No issues in this list.')),
        panel('Pull requests', sourceRows(project.pulls, (items) => items.map((pr) => pullRow(pr)), 'No pull requests returned.')),
        panel('Validation evidence', sourceRows(project.runs, (runs) => latest([...runs]).slice(0, 2)
          .map((run) => runRow(run, project.repository, project.runs)), 'No workflow runs returned.'),
        link('View job logs', '#homeci'))))));
}

function jobDetails(feed, key) {
  if (!feed) return null;
  const jobs = feed.data?.items;
  const summary = jobs ? `${jobs.length} of ${feed.data.total} jobs shown` : 'Job results';
  const details = element('details', '', element('summary', '', summary), sourceNote(feed),
    jobs?.length ? element('div', 'job-list', list(jobs.map((job) => row(
      link(job.title, job.url), runBadge(job),
      element('p', 'meta', element('code', '', `Job ${job.id}`)),
      meta(job.runner ? `Runner observed on this job: ${job.runner}` : 'Runner identity unavailable', job.selfHosted && 'Self-hosted',
        job.completed ? `Finished ${timestamp(job.completed)}` : job.started && `Started ${timestamp(job.started)}`),
      links(link('Job log', job.url)))))) : jobs && note('No jobs returned for this attempt.'));
  details.dataset.run = key;
  return details;
}

function candidateDetails(run, feed, duplicate) {
  const candidate = run.candidate;
  if (!candidate) return null;
  const jobs = feed?.data;
  let reason = candidate.reason;
  if (duplicate) reason = 'More than one run is linked to this task';
  else if (!reason && (run.state === 'queued' || run.state === 'blocked')) {
    reason = 'Waiting for GitHub to assign the job';
  } else if (!reason && run.state === 'running') reason = 'Verification in progress';
  else if (!reason && run.conclusion && run.conclusion !== 'success' && run.conclusion !== 'failure') {
    reason = `Workflow ${run.conclusion.replaceAll('_', ' ')}`;
  } else if (!reason && feed && freshness(feed) === 'stale') reason = 'Job evidence is stale';
  else if (!reason && (!jobs || jobs.total !== 1 || jobs.items.length !== 1)) {
    reason = 'Expected verification job unavailable';
  } else if (!reason) {
    const job = jobs.items[0].candidate;
    reason = job?.reason ?? (job?.passed && run.conclusion === 'success'
      ? 'GitHub reports the exact checkout and both suites passed. Approval and journal checks run separately.'
      : 'Successful workflow and job evidence was not observed');
  }
  return element('div', 'job-list',
    candidate.pr && element('p', 'meta', link(`DAF PR #${candidate.pr}`, candidate.prUrl)),
    candidate.commit && element('p', 'meta', 'DAF candidate ', element('code', '', candidate.commit)),
    note(reason));
}

function homeci(projects) {
  const forgeConfigured = projects.some(({ repository, visibility }) =>
    repository === 'samuelwhite/forge-homeci' && visibility === 'private');
  return element('div', 'stack',
    panel('Runner health', [element('div', 'runner-health', badge('unknown'),
      note('Live runner health is not connected. GitHub jobs show runner identities at the time of the job.'))]),
    !forgeConfigured && panel('Forge HomeCI', [
      element('div', 'runner-health', badge('unconfigured'),
        note('An operator can connect the private Forge-HomeCI Actions feed.')),
    ]),
    ...projects.map((project) => {
      const runners = new Map();
      for (const entry of project.runJobs) {
        for (const job of entry.jobs.data?.items ?? []) {
          if (job.selfHosted && job.runner && !runners.has(job.runnerId ?? job.runner)) {
            runners.set(job.runnerId ?? job.runner, { job, feed: entry.jobs });
          }
        }
      }
      const jobRows = (runs) => runs.map((run) => {
        const feed = project.runJobs.find((entry) => entry.runId === run.id && entry.attempt === run.attempt)?.jobs;
        const duplicate = run.candidate?.task &&
          runs.some((other) => other.id !== run.id && other.candidate?.task === run.candidate.task);
        return runRow(run, project.repository, project.runs, jobDetails(feed, run.url),
          candidateDetails(run, feed, duplicate));
      });
      const runnerRows = [...runners.values()].map(({ job, feed }) => {
        const stale = freshness(feed) === 'stale';
        return row(link(job.runner, job.url), badge(stale ? 'stale' : 'unknown',
          stale ? 'Stale evidence' : 'Health unknown'),
        meta(job.runnerId && `Runner ID ${job.runnerId}`, job.completed && `Job finished ${timestamp(job.completed)}`));
      });
      return projectSection(project, element('div', 'project-grid',
        panel('Workflow runs', sourceRows(project.runs, jobRows, 'No workflow runs returned.')),
        panel('Observed self-hosted runners', [runnerRows.length ? list(runnerRows) :
          note(project.runJobs.some((entry) => freshness(entry.jobs) === 'current')
            ? 'No self-hosted runner identities in the available jobs.' : 'Current job observations are unavailable.')])));
    }));
}

function documentPilot(item) {
  if (item === undefined) return null;
  if (item === null) return panel('Documentation pilot', [note('Attempt evidence is unavailable.')]);
  const states = {
    publishing: ['running', 'Publishing draft'], verifying: ['running', 'Checking HomeCI'],
    queued: ['queued', 'Queued for HomeCI'], review: ['completed', 'Ready for review'],
    finished: ['failed', 'Needs attention'],
  };
  const [state, label] = states[item.state] ?? [item.state, labels[item.state]];
  const codeRehearsal = item.kind === 'code-rehearsal';
  const simulated = codeRehearsal || item.kind === 'document-rehearsal';
  const evidence = !simulated && item.run && `${repoUrl(item.validator)}/actions/runs/${item.run}`;
  const reason = {
    branch_publish_outcome_unknown: 'Branch publication is uncertain. Resume the same attempt to check GitHub.',
    draft_create_outcome_unknown: 'Draft creation is uncertain. Resume the same attempt to check GitHub.',
    dispatch_outcome_unknown: 'Dispatch is uncertain. Resume the same attempt to look for the original run.',
    wrong_workflow_dispatch: 'Run metadata is incomplete or differs from the approved dispatch.',
    focused_test_failed: 'The focused Python test failed.',
    attempt_incomplete: 'This attempt was interrupted. Review the retained evidence before proceeding.',
  };
  return panel(codeRehearsal ? 'Code rehearsal' : simulated ? 'Documentation rehearsal' : 'Documentation pilot', [
    element('div', 'row', element('strong', '', item.task), badge(state, label)),
    meta(`Attempt ${item.attempt}`, item.file),
    element('p', 'meta', 'Candidate ', element('code', '', item.candidate)),
    item.taskSha && element('p', 'meta', 'Task SHA-256 ', element('code', '', item.taskSha)),
    item.validator && meta(item.validator, item.workflowId && `Workflow ${item.workflowId}`,
      item.workflowRevision && `Revision ${item.workflowRevision}`),
    item.runAttempt
      ? meta(`${simulated ? 'Simulated run' : 'Run'} ${item.run}`, `Attempt ${item.runAttempt}`,
        item.job && `${simulated ? 'Simulated job' : 'Job'} ${item.job}`,
        item.runner, item.conclusion && item.conclusion.replaceAll('_', ' '))
      : item.run && meta(`${simulated ? 'Reserved simulated run' : 'Reserved run'} ${item.run}`),
    item.reason && note(reason[item.reason] ?? item.reason.replaceAll('_', ' ')),
    simulated && item.pr && meta(`Simulated PR #${item.pr}`),
    !simulated && links(item.pr && link(`PR #${item.pr}`, `${repoUrl(item.repository)}/pull/${item.pr}`),
      evidence && (item.runAttempt
        ? link('HomeCI attempt', `${evidence}/attempts/${item.runAttempt}`)
        : link('HomeCI run', evidence)),
      evidence && item.job && link('Job log', `${evidence}/job/${item.job}`)),
  ]);
}

function render() {
  connection.dataset.alert = Boolean(connectionError);
  const count = snapshot?.projects.length;
  const available = snapshot?.projects.some((project) => ['milestones', 'issues', 'pulls', 'proposal', 'runs']
    .some((key) => freshness(project[key]) === 'current'));
  connection.textContent = connectionError || (loading ? 'Checking Mission Control…' :
    count === 0 ? 'No GitHub repositories configured.' :
      `${available ? 'GitHub sources checked' : 'GitHub data unavailable'} · ${timestamp(snapshot.reviewedAt)}`);
  if (!snapshot || !count) {
    content.replaceChildren(...(active === 'development' ? [development([])] : []));
    return;
  }
  const expanded = new Set([...content.querySelectorAll('details[open]')].map((item) => item.dataset.run));
  const focused = content.contains(document.activeElement) ? document.activeElement : null;
  const targets = focused ? [...content.querySelectorAll('a, summary')] : [];
  const focusKey = (item) => item.href || item.parentElement.dataset.run;
  const occurrence = focused && targets.filter((item) => focusKey(item) === focusKey(focused)).indexOf(focused);
  const view = ({ dashboard, development, homeci })[active](snapshot.projects);
  if (active !== 'dashboard') {
    const pilot = documentPilot(snapshot.documentPilot);
    if (pilot) view.prepend(pilot);
  }
  content.replaceChildren(view);
  for (const details of content.querySelectorAll('details')) details.open = expanded.has(details.dataset.run);
  if (occurrence >= 0 && focused) {
    [...content.querySelectorAll('a, summary')].filter((item) => focusKey(item) === focusKey(focused))[occurrence]
      ?.focus({ preventScroll: true });
  }
}

function route(focus) {
  const requested = location.hash.slice(1);
  if (requested === 'content') return;
  active = Object.hasOwn(views, requested) ? requested : 'dashboard';
  const [title, description] = views[active];
  document.title = `DAF · ${title}`;
  byId('heading').textContent = title;
  byId('description').textContent = description;
  byId('location').textContent = `Mission Control / ${title}`;
  for (const item of document.querySelectorAll('nav a')) {
    if (item.hash === `#${active}`) item.setAttribute('aria-current', 'page');
    else item.removeAttribute('aria-current');
  }
  if (snapshot || connectionError) render();
  if (focus) byId('heading').focus();
}

async function refresh() {
  if (loading) return;
  loading = true;
  button.setAttribute('aria-disabled', 'true');
  connection.textContent = 'Checking Mission Control…';
  try {
    const response = await fetch('/api/mission-control', { cache: 'no-store', signal: AbortSignal.timeout(20_000) });
    if (response.status === 401 || response.status === 403) {
      snapshot = undefined;
      connectionError = 'Viewer access is required. Reload and sign in to Mission Control.';
      return;
    }
    if (!response.ok) throw Error();
    const data = await response.json();
    if (!Array.isArray(data.projects) || !Number.isFinite(Date.parse(data.reviewedAt))) throw Error();
    snapshot = data;
    connectionError = undefined;
  } catch {
    if (snapshot && Date.now() - Date.parse(snapshot.reviewedAt) >= 24 * 60 * 60 * 1_000) snapshot = undefined;
    connectionError = snapshot ? 'Connection to Mission Control lost. Showing the last data received.' :
      'Cannot connect to Mission Control. Check your connection and refresh the view.';
  } finally {
    loading = false;
    button.removeAttribute('aria-disabled');
    render();
  }
}

window.addEventListener('hashchange', () => route(true));
button.addEventListener('click', refresh);
route(false);
refresh();
setInterval(() => { if (document.visibilityState === 'visible') refresh(); }, 5 * 60 * 1_000);

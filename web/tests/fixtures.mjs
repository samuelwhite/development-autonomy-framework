export const repository = 'example/project';
export const commit = 'a'.repeat(40);
export const baseline = 'b'.repeat(40);
export const updated = '2026-11-19T11:00:00Z';
export const title = '<img src=x onerror=alert(1)> Review the release';
export const entry = { repository, visibility: 'public', planning: true,
  plan: { path: 'docs/plan.json', commit } };
export const password = 'test-only-viewer-password-1234';
export const token = 'test_only_git_token';

export const run = { id: 123, run_attempt: 2, workflow_id: 789, path: '.github/workflows/ci.yml',
  name: 'Release checks', head_sha: commit, status: 'completed', conclusion: 'failure',
  updated_at: updated, head_branch: 'main', html_url: 'javascript:alert(1)' };

export const job = { id: 456, name: 'Validate changes', run_id: run.id, run_attempt: run.run_attempt,
  head_sha: commit, status: 'completed', conclusion: 'failure', started_at: updated,
  completed_at: updated, runner_id: 19, runner_name: 'observed-runner', labels: ['self-hosted'],
  html_url: 'https://example.invalid/unsafe' };

export const plan = { schema_version: 1, plan: { schema_version: 1, plan_id: 'release-readiness',
  repository, baseline_revision: baseline, milestones: [{ id: 'REVIEW', deliverable: 'Review release readiness' }] },
  tasks: [{ milestone_id: 'REVIEW', instruction: 'Review evidence with the Product Manager.' }] };

export const file = (document = plan) => ({ type: 'file', path: entry.plan.path, encoding: 'base64',
  sha: 'c'.repeat(40), content: Buffer.from(JSON.stringify(document)).toString('base64') });

export function githubFixture(url) {
  const path = new URL(url).pathname.split('/').slice(4).join('/');
  if (path === 'milestones') return Response.json([
    { number: 7, title: 'Release readiness', state: 'open', open_issues: 3, closed_issues: 1, updated_at: updated },
  ]);
  if (path === 'issues') return Response.json([
    { number: 4, title, state: 'open', labels: [{ name: 'product decision' }], updated_at: updated },
    { number: 5, pull_request: {} },
  ]);
  if (path === 'pulls') return Response.json([
    { number: 6, title: 'Developer review', state: 'open', draft: true, merged_at: null,
      updated_at: updated, head: { sha: commit } },
  ]);
  if (path === 'contents/docs/plan.json') return Response.json(file());
  if (path === 'actions/runs') return Response.json({ workflow_runs: [run] });
  if (path === 'actions/runs/123/attempts/2/jobs') return Response.json({ total_count: 1, jobs: [job] });
  throw Error(`Unexpected fixture path ${path}`);
}

export async function listen(app) {
  await new Promise((resolve) => app.http.listen(0, '127.0.0.1', resolve));
  return `http://127.0.0.1:${app.http.address().port}`;
}

import { closeSync, constants, fstatSync, openSync, readSync } from 'node:fs';
import { SHA } from './config.mjs';

const limit = 8192;
const atom = /^[a-zA-Z0-9_.-]{1,120}$/;
const document = /^docs\/(?:[a-zA-Z0-9_-][a-zA-Z0-9_.-]*\/)*[a-zA-Z0-9_-][a-zA-Z0-9_.-]*\.md$/;
const states = ['publishing', 'verifying', 'running', 'queued', 'blocked', 'finished', 'review'];
const conclusions = ['success', 'failure', 'cancelled', 'skipped', 'timed_out', 'neutral',
  'action_required', 'stale', 'startup_failure'];
const integer = (value) => Number.isSafeInteger(value) && value > 0;
const matches = (pattern, value) => typeof value === 'string' && pattern.test(value);

export function readDocumentPilot(path, repositories) {
  if (!path) return undefined;
  let descriptor;
  try {
    descriptor = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
    if (!fstatSync(descriptor).isFile()) return null;
    const bytes = Buffer.alloc(limit + 1);
    const size = readSync(descriptor, bytes);
    if (!size || size > limit) return null;
    const item = JSON.parse(bytes.subarray(0, size).toString('utf8'));
    if (item?.schema_version !== 1 || !repositories.some(r => r.repository === item.repository) ||
        !matches(atom, item.task) || !matches(atom, item.attempt) ||
        !matches(document, item.file) || item.file.length > 240 ||
        !matches(SHA, item.candidate_sha) || !states.includes(item.state)) return null;
    const validator = repositories.find(r => r.visibility === 'private' &&
      r.repository === item.validator_repository)?.repository;
    const run = validator && integer(item.run_id) ? item.run_id : null;
    const attempt = run && item.run_attempt === 1 ? 1 : null;
    return {
      task: item.task, attempt: item.attempt, file: item.file, candidate: item.candidate_sha,
      state: item.state, reason: matches(/^[a-z_]{1,80}$/, item.reason) ? item.reason : null,
      pr: integer(item.draft_pr) ? item.draft_pr : null,
      repository: item.repository, validator, run, runAttempt: attempt,
      job: attempt && integer(item.job_id) ? item.job_id : null,
      runner: attempt && matches(atom, item.runner) ? item.runner : null,
      conclusion: attempt && conclusions.includes(item.conclusion) ? item.conclusion : null,
    };
  } catch {
    return null;
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
  }
}

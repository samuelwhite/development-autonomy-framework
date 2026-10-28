const { test } = require('node:test');
const assert = require('node:assert/strict');
const sim = require('./simulation.js');

function setup(provider = 'codex', mode = 'review') {
  const s = sim.initial();
  sim.next(s); sim.configuration(s, 'provider', provider); sim.next(s);
  sim.connect(s); sim.next(s); sim.configuration(s, 'mode', mode); sim.next(s);
  return s;
}
function ready(mode = 'review', scenario = 'normal', kind = 'documentation') {
  const s = setup('codex', mode);
  assert.equal(sim.verify(s), true);
  sim.chooseTask(s, kind); s.scenario = scenario;
  assert.equal(sim.prepare(s), true); assert.equal(sim.start(s), true);
  return s;
}
test('no provider is selected; the safest permission is the default', () => {
  const s = sim.initial(); assert.equal(s.provider, ''); assert.equal(s.mode, 'review');
  sim.next(s); assert.equal(sim.next(s), false); assert.equal(s.step, 1);
  assert.equal(sim.connect(s), false); assert.equal(sim.configuration(s, 'provider', 'ollama'), false);
});
for (const provider of ['codex', 'claude']) {
  test(`${provider}: automatic checks precede suggested task start`, () => {
    const s = setup(provider); assert.equal(s.step, 5); assert.equal(s.checkStatus, 'checking');
    assert.equal(sim.prepare(s), false); assert.equal(sim.next(s), false);
    assert.equal(sim.verify(s), true); assert.equal(s.step, 6);
    assert.equal(sim.prepare(s), true); assert.equal(sim.start(s), true);
    assert.equal(sim.start(s), false); assert.equal(s.attempt, 1);
  });
}
for (const issue of ['connection', 'permissions', 'limits']) {
  test(`${issue}: retry retains failure; explicit fix must recheck`, () => {
    const s = setup('claude', 'edit'); s.setupIssue = issue;
    assert.equal(sim.verify(s), false); assert.equal(s.checkError, issue);
    assert.equal(sim.prepare(s), false); assert.equal(sim.next(s), false);
    sim.beginCheck(s); assert.equal(sim.verify(s), false);
    assert.equal(sim.fixCheck(s), true); assert.equal(s.verified, false);
    assert.equal(s.checkStatus, 'checking'); assert.equal(sim.prepare(s), false);
    assert.equal(sim.verify(s), true); assert.equal(s.step, 6);
    if (issue === 'permissions') assert.equal(s.mode, 'review');
    if (issue === 'limits') { assert.equal(s.tokens, 1000); assert.equal(s.minutes, 5); }
  });
}
test('going back cancels a pending check; changing permissions requires new checks', () => {
  const s = setup(); sim.back(s); assert.equal(s.step, 4);
  assert.equal(sim.verify(s), false); sim.configuration(s, 'mode', 'edit');
  sim.next(s); sim.verify(s); sim.back(s);
  assert.equal(s.verified, false); assert.equal(sim.prepare(s), false);
});
for (const kind of ['documentation', 'review', 'plan']) {
  test(`${kind}: a suggested task needs no custom prompt and cannot edit in suggestions mode`, () => {
    const s = ready('review', 'normal', kind);
    assert.equal(s.customTask, ''); sim.tick(s); sim.tick(s);
    assert.equal(s.status, 'validating'); assert.equal(s.approval, null);
    sim.tick(s); assert.equal(s.status, 'completed'); assert.equal(s.used, 800);
    assert.equal(sim.milestones(s).filter(m => m.state === 'done').length, 3);
    assert.match(s.events.at(-1).text, /Nothing was changed/);
  });
}
for (const kind of ['plan', 'review']) {
  test(`${kind}: edit permission does not turn a suggestions task into a change`, () => {
    const s = ready('edit', 'normal', kind); sim.tick(s); sim.tick(s);
    assert.equal(s.status, 'validating'); assert.equal(s.approval, null);
  });
}
test('custom prompt is optional, bounded and stored as text', () => {
  const s = setup(); sim.verify(s); sim.chooseTask(s, 'custom');
  for (const text of ['', '  ', 'x'.repeat(501)]) { s.customTask = text; assert.equal(sim.prepare(s), false); }
  s.customTask = '<img src=x onerror=alert(1)>'; assert.equal(sim.prepare(s), true);
  assert.equal(s.task, '<img src=x onerror=alert(1)>');
});
test('approval is bound to the current request and consumed exactly once', () => {
  const s = ready('edit'); sim.tick(s); sim.tick(s);
  assert.equal(s.status, 'awaiting_approval');
  assert.equal(sim.decide(s, s.approval + 1, true), false);
  const id = s.approval; assert.equal(sim.decide(s, id, true), true);
  assert.equal(s.status, 'validating'); assert.equal(sim.decide(s, id, true), false);
  sim.tick(s); assert.equal(s.status, 'completed');
});
test('denial stops the task and never applies a change', () => {
  const s = ready('edit'); sim.tick(s); sim.tick(s); sim.decide(s, s.approval, false); sim.tick(s);
  assert.equal(s.status, 'stopped'); assert.equal(s.stopReason, 'denied'); assert.equal(s.reserved, 0);
});
for (const phase of ['running', 'awaiting_approval', 'validating']) {
  test(`stop during ${phase} invalidates queued steps and approvals`, () => {
    const s = ready('edit');
    if (phase !== 'running') { sim.tick(s); sim.tick(s); }
    const id = s.approval;
    if (phase === 'validating') sim.decide(s, id, true);
    sim.stop(s); sim.tick(s); assert.equal(s.status, 'stopped');
    assert.equal(s.approval, null); assert.equal(sim.decide(s, id, true), false);
    assert.equal(sim.start(s), false);
  });
  test(`reload during ${phase} retains the reservation and original attempt`, () => {
    const s = ready('edit');
    if (phase !== 'running') { sim.tick(s); sim.tick(s); }
    if (phase === 'validating') sim.decide(s, s.approval, true);
    const restored = sim.restore(JSON.stringify(s));
    assert.equal(restored.status, 'uncertain'); assert.equal(restored.reserved, 800);
    assert.equal(restored.returnNotice, true); assert.equal(sim.start(restored), false);
    sim.stop(restored); assert.equal(restored.status, 'uncertain');
    sim.reconcile(restored); assert.equal(restored.status, 'stopped');
    assert.equal(restored.attempt, 1); assert.equal(restored.reserved, 0);
  });
}
test('unavailable recovery never releases a reservation or creates duplicate work', () => {
  const s = ready(); sim.disconnect(s); s.recoveryUnavailable = true;
  for (let i = 0; i < 3; i++) assert.equal(sim.reconcile(s), false);
  assert.equal(s.status, 'uncertain'); assert.equal(s.reserved, 800); assert.equal(s.attempt, 1);
  s.recoveryUnavailable = false; assert.equal(sim.reconcile(s), true);
  assert.equal(s.attempt, 1); assert.equal(sim.reconcile(s), false);
});
for (const mode of ['review', 'edit']) {
  test(`${mode}: failed independent result check never completes or retries`, () => {
    const s = ready(mode, 'check-failure'); sim.tick(s); sim.tick(s);
    if (mode === 'edit') sim.decide(s, s.approval, true);
    sim.tick(s); assert.equal(s.status, 'failed'); assert.equal(s.phase, 2);
    assert.equal(sim.start(s), false);
  });
}
for (const ceiling of [1000, 2000]) {
  test(`budget refusal at ${ceiling} tokens does not raise limits`, () => {
    const s = ready('review', 'limit'); s.tokens = ceiling; sim.tick(s); sim.tick(s);
    assert.equal(s.status, 'limited'); assert.equal(s.tokens, ceiling);
    assert.equal(s.phase, 1); assert.equal(sim.start(s), false);
  });
}
test('connection-loss scenario blocks before recording unobserved progress', () => {
  const s = ready('review', 'connection-lost'); sim.tick(s); sim.tick(s);
  assert.equal(s.status, 'uncertain'); assert.equal(s.reserved, 800); assert.equal(s.phase, 1);
});
test('time limit includes waiting for approval', () => {
  const s = ready('edit'); sim.tick(s); sim.tick(s);
  sim.elapse(s, 299); assert.equal(s.status, 'awaiting_approval');
  sim.elapse(s, 1); assert.equal(s.status, 'stopped'); assert.equal(s.stopReason, 'time');
});
test('configuration cannot change on an active plan', () => {
  const s = ready(); assert.equal(sim.configuration(s, 'tokens', 2000), false);
  assert.equal(sim.configuration(s, 'mode', 'edit'), false);
});
test('completed results and history remain available on return', () => {
  const s = ready('review', 'normal', 'plan'); sim.tick(s); sim.tick(s); sim.tick(s);
  s.view = 'results'; const restored = sim.restore(JSON.stringify(s));
  assert.equal(restored.status, 'completed'); assert.equal(restored.view, 'results');
  assert.deepEqual(restored.events, s.events); assert.equal(restored.taskKind, 'plan');
});
test('old, corrupt, prototype-key and inconsistent state cannot restore a runnable task', () => {
  const initial = sim.initial();
  for (const raw of [null, 'not-json', '{}', JSON.stringify({...initial, version:1}),
    JSON.stringify({...initial, step:7}), JSON.stringify({...initial, tokens:Infinity}),
    JSON.stringify({...initial, provider:'toString'}), JSON.stringify({...initial, project:'constructor'}),
    JSON.stringify({...initial, checkStatus:'failed', checkError:null}),
    JSON.stringify({...initial, events:[{id:1,text:{}}]})]) assert.deepEqual(sim.restore(raw), initial);
});

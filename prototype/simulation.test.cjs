const { test } = require('node:test');
const assert = require('node:assert/strict');
const sim = require('./simulation.js');

function ready(mode = 'review', scenario = 'normal') {
  const s = sim.initial();
  s.connected = true; s.mode = mode; s.scenario = scenario;
  sim.verify(s); s.step = 6;
  assert.equal(sim.prepare(s, s.task), true);
  assert.equal(sim.start(s), true);
  return s;
}
for (const provider of ['codex', 'claude']) {
  test(`${provider}: setup requires connection and verification`, () => {
    const s = sim.initial(); s.provider = provider; s.step = 2;
    assert.equal(sim.next(s), false);
    assert.equal(sim.verify(s), false);
    s.connected = true;
    assert.equal(sim.next(s), true);
    s.step = 5;
    assert.equal(sim.next(s), false);
    assert.equal(sim.verify(s), true);
    assert.equal(sim.next(s), true);
    assert.equal(sim.prepare(s, '  '), false);
    assert.equal(sim.prepare(s, 'x'.repeat(501)), false);
    assert.equal(sim.prepare(s, 'Review the sample'), true);
  });
}
test('read-only path never asks for a write or accepts code changes', () => {
  const s = ready(); sim.tick(s); sim.tick(s);
  assert.equal(s.status, 'completed'); assert.equal(s.approval, null);
  assert.equal(s.used, 800); assert.equal(s.reserved, 0);
  assert.match(s.events.at(-1).text, /No write permission/);
});
test('one-time edit approval precedes independent simulated validation', () => {
  const s = ready('edit'); sim.tick(s); sim.tick(s);
  assert.equal(s.status, 'awaiting_approval');
  assert.equal(sim.decide(s, s.approval + 1, true), false);
  const id = s.approval;
  assert.equal(sim.decide(s, id, true), true);
  assert.equal(s.status, 'validating');
  assert.equal(sim.decide(s, id, true), false);
  sim.tick(s); assert.equal(s.status, 'completed');
});
test('denied permission ends the attempt', () => {
  const s = ready('edit'); sim.tick(s); sim.tick(s);
  sim.decide(s, s.approval, false); sim.tick(s);
  assert.equal(s.status, 'stopped'); assert.equal(s.reserved, 0);
});
for (const phase of ['running', 'awaiting_approval', 'validating']) {
  test(`stop in ${phase} invalidates queued actions`, () => {
    const s = ready('edit');
    if (phase !== 'running') { sim.tick(s); sim.tick(s); }
    const id = s.approval;
    if (phase === 'validating') sim.decide(s, id, true);
    sim.stop(s); sim.tick(s);
    assert.equal(s.status, 'stopped'); assert.equal(s.approval, null);
    assert.equal(sim.decide(s, id, true), false); assert.equal(sim.start(s), false);
  });
  test(`reload in ${phase} blocks and reconciles the existing attempt`, () => {
    const s = ready('edit');
    if (phase !== 'running') { sim.tick(s); sim.tick(s); }
    if (phase === 'validating') sim.decide(s, s.approval, true);
    const restored = sim.restore(JSON.stringify(s));
    assert.equal(restored.status, 'uncertain'); assert.equal(restored.reserved, 800);
    assert.equal(sim.start(restored), false);
    sim.stop(restored); assert.equal(restored.status, 'uncertain');
    sim.reconcile(restored);
    assert.equal(restored.status, 'stopped'); assert.equal(restored.attempt, 1);
    assert.equal(restored.reserved, 0); assert.equal(sim.reconcile(restored), false);
  });
}
test('failed independent check cannot complete or retry the task', () => {
  const s = ready('edit', 'check-failure'); sim.tick(s); sim.tick(s);
  sim.decide(s, s.approval, true); sim.tick(s);
  assert.equal(s.status, 'failed'); assert.equal(sim.start(s), false);
});
for (const ceiling of [1000, 2000]) {
  test(`budget refusal at ${ceiling} tokens never retries or increases limits`, () => {
    const s = ready('review', 'limit'); s.tokens = ceiling;
    sim.tick(s); sim.tick(s);
    assert.equal(s.status, 'limited'); assert.equal(s.tokens, ceiling);
    assert.equal(s.attempt, 1); assert.equal(sim.start(s), false);
  });
}
test('connection loss preserves reservation and rejects duplicate start', () => {
  const s = ready('review', 'connection-lost'); sim.tick(s); sim.tick(s);
  assert.equal(s.status, 'uncertain'); assert.equal(s.reserved, 800);
  assert.equal(sim.start(s), false); assert.equal(s.attempt, 1);
});
test('time limit includes time waiting for approval', () => {
  const s = ready('edit'); sim.tick(s); sim.tick(s);
  sim.elapse(s, 299); assert.equal(s.status, 'awaiting_approval');
  sim.elapse(s, 1); assert.equal(s.status, 'stopped');
});
test('changing configuration invalidates verification; active plans cannot change', () => {
  const s = sim.initial(); s.connected = true; sim.verify(s);
  sim.configuration(s, 'mode', 'edit'); assert.equal(s.verified, false);
  sim.verify(s); sim.configuration(s, 'provider', 'claude');
  assert.equal(s.connected, false); assert.equal(s.verified, false);
  assert.equal(sim.configuration(s, 'provider', 'ollama'), false);
  const running = ready();
  assert.equal(sim.configuration(running, 'tokens', 2000), false);
});
test('failed verification blocks progression', () => {
  const s = sim.initial(); s.connected = true; s.step = 5;
  sim.verify(s); sim.verify(s, true); assert.equal(sim.next(s), false);
});
test('corrupt, foreign and inconsistent browser state resets safely', () => {
  for (const raw of [null, 'not-json', '{}', '{"version":2}', JSON.stringify({...sim.initial(), step: 7}),
    JSON.stringify({...sim.initial(), tokens: Infinity}), JSON.stringify({...sim.initial(), provider:'live'}),
    JSON.stringify({...sim.initial(), events:[{id:1,text:{}}]})]) {
    assert.deepEqual(sim.restore(raw), sim.initial());
  }
});

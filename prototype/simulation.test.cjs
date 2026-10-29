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

function planned(scenario = 'normal', kind = 'documentation', provider = 'codex') {
  const s = setup(provider, 'independent'); sim.verify(s); sim.chooseTask(s, kind);
  sim.selectScenario(s, scenario); assert.equal(sim.reviewPlan(s), true);
  for (const key of ['plan', 'scope', 'limits']) assert.equal(sim.consent(s, key, true), true);
  assert.equal(sim.approvePlan(s), true); return s;
}
function checkpoint(s) { sim.tick(s); sim.tick(s); assert.equal(s.status, 'milestone_review'); }

test('independent work requires explicit plan, scope and limit consent before any start', () => {
  const s = setup('codex', 'independent'); sim.verify(s);
  assert.equal(sim.prepare(s), false); assert.equal(sim.start(s), false);
  assert.equal(sim.approvePlan(s), false); assert.equal(sim.reviewPlan(s), true);
  for (const key of ['plan', 'scope']) { sim.consent(s, key, true); assert.equal(sim.approvePlan(s), false); }
  assert.equal(s.attempt, 0); assert.equal(s.used, 0); assert.equal(s.reserved, 0);
  sim.consent(s, 'limits', true); assert.equal(sim.approvePlan(s), true);
  assert.equal(s.attempt, 1); assert.equal(s.reserved, 800); assert.equal(s.status, 'running');
  assert.equal(sim.approvePlan(s), false); assert.equal(sim.start(s), false);
  assert.equal(sim.configuration(s, 'mode', 'edit'), false);
});

test('changed plan details invalidate consent and cannot use a stale plan approval', () => {
  for (const [key, value] of [['tokens', 2000], ['minutes', 10], ['project', 'Little Library'], ['provider', 'claude']]) {
    const s = setup('codex', 'independent'); sim.verify(s); sim.reviewPlan(s);
    for (const key of ['plan','scope','limits']) sim.consent(s, key, true);
    s[key] = value; // Stale displayed-plan race, independent of the UI's configuration guard.
    assert.equal(sim.approvePlan(s), false); assert.equal(s.attempt, 0);
  }
  for (const change of [s => sim.chooseTask(s, 'plan'), s => sim.selectScenario(s, 'scope'), s => sim.back(s)]) {
    const s = setup('codex','independent'); sim.verify(s); sim.reviewPlan(s);
    for (const key of ['plan','scope','limits']) sim.consent(s,key,true);
    change(s); assert.equal(s.planDraft, null); assert.equal(s.approvedPlan, null);
    assert.deepEqual(s.consents, {plan:false,scope:false,limits:false}); assert.equal(sim.approvePlan(s), false);
  }
});

for (const provider of ['codex','claude']) {
  test(`${provider}: three verified milestones each pause, without per-edit permission`, () => {
    const s = planned('normal','documentation',provider), scope = s.approvedPlan;
    for (let index = 0; index < 3; index++) {
      sim.tick(s); assert.equal(s.status, 'validating');
      assert.equal(s.approval, null); assert.equal(s.milestoneResults[index].check, 'pending');
      assert.equal(sim.reviewMilestone(s, s.approval, true), false);
      sim.tick(s); assert.equal(s.status, 'milestone_review');
      assert.equal(s.milestoneResults[index].check, 'passed');
      assert.equal(s.milestoneResults[index].reviewed, false);
      const id = s.approval, snapshot = JSON.stringify(s);
      sim.tick(s); sim.tick(s); assert.equal(JSON.stringify(s), snapshot);
      assert.equal(sim.decide(s, id, true), false); // Edit permission cannot acknowledge a milestone.
      assert.equal(sim.reviewMilestone(s, id + 1, true), false);
      assert.equal(sim.reviewMilestone(s, id, true), true);
      assert.equal(sim.reviewMilestone(s, id, true), false);
      assert.equal(s.approvedPlan, scope); assert.equal(s.attempt, 1);
    }
    assert.equal(s.status, 'completed'); assert.equal(s.used, 800); assert.equal(s.reserved, 0);
    assert.equal(s.milestoneResults.filter(m => m.reviewed).length, 3);
    const plan = JSON.parse(scope);
    for (const forbidden of ['Publication','Merging','Deployment']) assert.ok(plan.blocked.includes(forbidden));
    assert.match(s.events.at(-1).text, /Nothing was published, merged, deployed/);
    const restored = sim.restore(JSON.stringify(s));
    assert.equal(restored.status, 'completed'); assert.deepEqual(restored.milestoneResults, s.milestoneResults);
  });
}
for (const kind of ['review','plan']) {
  test(`independent ${kind} remains written work only, with no editing authority`, () => {
    const s = planned('normal', kind); assert.equal(sim.edits(s), false);
    assert.match(sim.planFor(s).scope, /No changes to the example project/);
    for (let i=0;i<3;i++) { checkpoint(s); sim.reviewMilestone(s,s.approval,true); }
    assert.equal(s.status, 'completed'); assert.equal(sim.edits(s), false);
  });
}
for (const kind of sim.exceptions) {
  test(`${kind} exception: successful validation cannot expand the approved plan`, () => {
    const s = planned(kind), plan = s.approvedPlan;
    checkpoint(s); sim.reviewMilestone(s, s.approval, true);
    const before = {used:s.used, reserved:s.reserved, records:JSON.stringify(s.milestoneResults)};
    sim.tick(s); assert.equal(s.status, 'boundary_pause'); assert.equal(s.exception, kind);
    assert.equal(s.approvedPlan, plan); assert.equal(s.approval, null);
    for (let n=0;n<4;n++) sim.tick(s);
    assert.deepEqual({used:s.used,reserved:s.reserved,records:JSON.stringify(s.milestoneResults)}, before);
    assert.equal(sim.reviewMilestone(s, 1, true), false); assert.equal(sim.approvePlan(s), false);
    assert.equal(sim.start(s), false); assert.equal(sim.configuration(s,'tokens',2000), false);
  });
}
for (const phase of ['running','validating','milestone_review','boundary_pause']) {
  test(`independent ${phase}: stop and reload revoke pending decisions without losing work`, () => {
    const s = planned();
    if (phase !== 'running') sim.tick(s);
    if (['milestone_review','boundary_pause'].includes(phase)) sim.tick(s);
    if (phase === 'boundary_pause') sim.raiseException(s, 'unexpected');
    assert.equal(s.status, phase);
    const id = s.approval, held = s.reserved, used = s.used, work = JSON.stringify(s.milestoneResults);
    const restored = sim.restore(JSON.stringify(s));
    assert.equal(restored.status, 'uncertain'); assert.equal(restored.approval, null);
    assert.equal(restored.reserved, held); assert.equal(restored.used, used);
    assert.equal(JSON.stringify(restored.milestoneResults), work);
    restored.recoveryUnavailable = true; assert.equal(sim.reconcile(restored), false);
    sim.stop(restored); assert.equal(restored.status,'uncertain'); assert.equal(restored.reserved,held);
    restored.recoveryUnavailable = false; assert.equal(sim.reconcile(restored), true);
    assert.equal(restored.attempt,1); assert.equal(restored.status,'stopped');
    assert.equal(restored.used,used); assert.equal(restored.reserved,0);
    sim.stop(s); sim.tick(s); assert.equal(s.status,'stopped'); assert.equal(s.used,used);
    assert.equal(JSON.stringify(s.milestoneResults),work); assert.equal(sim.reviewMilestone(s,id,true),false);
  });
}
for (const phase of ['running','validating','milestone_review']) {
  test(`immediate exception during ${phase} blocks the next callback and invalidates review`, () => {
    const s = planned();
    if (phase !== 'running') sim.tick(s);
    if (phase === 'milestone_review') sim.tick(s);
    const id = s.approval;
    assert.equal(sim.raiseException(s,'permissions'),true);
    const snapshot = JSON.stringify(s); sim.tick(s); assert.equal(JSON.stringify(s),snapshot);
    assert.equal(sim.reviewMilestone(s,id,true),false); assert.equal(s.status,'boundary_pause');
  });
}
test('changing approved scope or limits cannot continue after a passed milestone', () => {
  for (const [key,value] of [['tokens',2000],['minutes',10],['project','Little Library'],['taskKind','review']]) {
    const s = planned(); checkpoint(s); s[key]=value;
    assert.equal(sim.reviewMilestone(s,s.approval,true),false); assert.equal(s.status,'boundary_pause');
    assert.equal(s.milestoneResults.length,1); assert.equal(s.used,250);
  }
});
test('failed milestone evidence blocks all later work and is not silently accepted', () => {
  const s = planned('check-failure'); sim.tick(s); sim.tick(s);
  assert.equal(s.status,'failed'); assert.equal(s.milestoneResults[0].check,'failed');
  assert.equal(s.phase,0); assert.equal(s.reserved,0);
  assert.equal(sim.reviewMilestone(s,null,true),false); sim.tick(s); assert.equal(s.status,'failed');
  assert.equal(sim.restore(JSON.stringify(s)).status,'failed');
});
test('declining milestone review keeps completed work and stops the remaining plan', () => {
  const s = planned(); checkpoint(s); sim.reviewMilestone(s,s.approval,false);
  assert.equal(s.status,'stopped'); assert.equal(s.stopReason,'milestone_declined');
  assert.equal(s.milestoneResults[0].check,'passed'); assert.equal(s.milestoneResults[0].reviewed,false);
  assert.equal(s.used,250); assert.equal(s.reserved,0); sim.tick(s); assert.equal(s.phase,1);
});
test('time expiry during a milestone review cancels its decision and never extends limits', () => {
  const s = planned(); checkpoint(s); const id=s.approval;
  sim.elapse(s,300); assert.equal(s.status,'stopped'); assert.equal(s.stopReason,'time');
  assert.equal(s.approval,null); assert.equal(sim.reviewMilestone(s,id,true),false); assert.equal(s.minutes,5);
});
test('independent connection loss does not record unobserved work', () => {
  const s=planned('connection-lost'); sim.tick(s);
  assert.equal(s.status,'uncertain'); assert.equal(s.reserved,800); assert.equal(s.milestoneResults.length,0);
});
test('malformed plan storage cannot restore approved work or fabricate completed reviews', () => {
  const s=planned(); checkpoint(s);
  for (const bad of [{...s,approvedPlan:null}, {...s,approvedPlan:'{}'}, {...s,phase:3,status:'completed'},
    {...s,milestoneResults:[{index:0,check:'pending',reviewed:true}]}, {...s,consents:null},
    {...s,consents:{plan:true,scope:false,limits:true}},
    {...s,status:'boundary_pause',exception:null}]) assert.deepEqual(sim.restore(JSON.stringify(bad)),sim.initial());
});
test('previous suggestion/edit state retains its history and unknown allowance on upgrade', () => {
  const s=ready('edit'); sim.tick(s); sim.tick(s); s.version=2;
  for(const key of ['planReview','planDraft','consents','approvedPlan','milestoneResults','exception']) delete s[key];
  const restored=sim.restore(JSON.stringify(s)); assert.equal(restored.version,3);
  assert.equal(restored.status,'uncertain'); assert.equal(restored.reserved,800); assert.equal(restored.attempt,1);
  assert.deepEqual(restored.events.slice(0,-1),s.events);
});

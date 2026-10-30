'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {schema,validate,source,strictJSON,response} = require('../planning-contract.cjs');
const {validSender,installPlanningIPC} = require('../planning-ipc.cjs');
const selected={repository:'owner/repo',commit_sha:'a'.repeat(40),path:'plans/work.json'};
const request={protocol:1,requestId:'a'.repeat(32),operation:'planning.importPublicPlan',source:selected};
test('protocol accepts only three typed operations and rejects authority/path injections',()=>{
  validate(request,schema.$defs.request); source(selected);
  for(const extra of [{operation:'execute'},{protocol:true},{command:'whoami'},{approval:true},{storage:'/tmp'}]) assert.throws(()=>validate({...request,...extra},schema.$defs.request));
  for(const path of ['../work.json','plans/CON.json','/plan.json','plans//work.json','plans/.GIT/work.json','plans/a./work.json','plans\\work.json','plans/%2e.json']) assert.throws(()=>source({...selected,path}));
  assert.throws(()=>source({...selected,headers:{Authorization:'test'}}));
});
test('bounded strict JSON refuses duplicate keys, extra messages and nonfinite values',()=>{
  for(const text of ['{"a":1,"a":2}','{"a":{"b":1,"b":2}}','{}\n{}','{"x":NaN}','{"x":1e999}','[1,]','{"a":1,}','"bad\nstring"','[', '{"a":', ' '.repeat(4)]) assert.throws(()=>strictJSON(Buffer.from(text)),text);
  assert.throws(()=>strictJSON(Buffer.from([0xff])));
  assert.equal(strictJSON(Buffer.from('{"__proto__":{"x":1}}')).__proto__.x,1);
  assert.equal({}.x,undefined);
  assert.equal(strictJSON(Buffer.from(' {"x":"a\\n\\\"b","y":[true,false,null,2.5]}\n')).x,'a\n"b');
});
test('response refuses mismatched IDs, success on wrong operation and forged authority',()=>{
  const refused={protocol:1,requestId:request.requestId,outcome:'refused',error:{code:'invalid_plan'}};
  response(refused,request);
  assert.throws(()=>response({...refused,requestId:'b'.repeat(32)},request));
  assert.throws(()=>response({...refused,error:{code:'raw secret'}},request));
  assert.throws(()=>response({protocol:1,requestId:request.requestId,outcome:'listed',imports:[],damaged:[]},request));
});
function setup(answer=1) {
  const handlers={}, calls=[]; const frame={url:'daf://app/planning.html'};
  const contents={mainFrame:frame,getURL:()=>frame.url}; const win={isDestroyed:()=>false,webContents:contents};
  const event={sender:contents,senderFrame:frame};
  const runner={active:null,run:async(...args)=>{calls.push(args);return 'called';},cancel:async()=>{calls.push(['cancel']);}};
  const dialog={showMessageBox:async(_win,options)=>{calls.push(['consent',options]);return {response:answer};}};
  const cancel=installPlanningIPC({ipcMain:{handle:(name,handler)=>{handlers[name]=handler;}},dialog,win,runner});
  return {handlers,calls,frame,contents,win,event,runner,dialog,cancel};
}
test('sender validation rejects subframes, stale windows and demo pages',()=>{
  const x=setup(); assert.equal(validSender(x.event,x.win),true);
  assert.equal(validSender({...x.event,senderFrame:{url:x.frame.url}},x.win),false);
  assert.equal(validSender({...x.event,sender:{}},x.win),false);
  x.frame.url='daf://app/index.html'; assert.equal(validSender(x.event,x.win),false);
});
test('only explicit native confirmation permits a network operation',async()=>{
  const x=setup(0);
  const refused=await x.handlers['planning:import'](x.event,selected); assert.equal(refused.error.code,'read_not_approved'); assert.equal(x.calls.length,1);
  x.dialog.showMessageBox=async()=>({response:1});
  assert.equal(await x.handlers['planning:import'](x.event,selected),'called');
  assert.deepEqual(x.calls[1],['planning.importPublicPlan',{source:selected}]);
  assert.equal((await x.handlers['planning:list'](x.event,'unexpected')).error.code,'invalid_request');
});
test('cancel during confirmation invalidates delayed approval',async()=>{
  const x=setup(); let finish;
  x.dialog.showMessageBox=()=>new Promise(resolve=>{finish=resolve;});
  const pending=x.handlers['planning:import'](x.event,selected);
  await x.cancel(); finish({response:1});
  assert.equal((await pending).error.code,'read_not_approved'); assert.deepEqual(x.calls,[['cancel']]);
});
test('shared response corpus rejects trust, dependency and source-binding changes',()=>{
  const view=require('./fixtures/untrusted-view.json');
  const get={protocol:1,requestId:'a'.repeat(32),operation:'planning.getImport',id:view.id};
  const good={protocol:1,requestId:get.requestId,outcome:'loaded',snapshot:view};response(good,get);
  for(const change of [v=>{v.executionAuthority=true;},v=>{v.spendingAuthority=true;},v=>{v.approval={trusted:true};},v=>{v.trusted=true;},v=>{v.milestones[0].dependencies=['F2'];},v=>{v.id='b'.repeat(64);}]) {
    const altered=structuredClone(good);change(altered.snapshot);assert.throws(()=>response(altered,get));
  }
  const importRequest={...request,source:{repository:view.source.repository,commit_sha:'b'.repeat(40),path:view.source.path}};
  assert.throws(()=>response({...good,outcome:'imported'},importRequest));
});

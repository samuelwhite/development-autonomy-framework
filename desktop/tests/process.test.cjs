'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {PlanningProcess} = require('../planning-process.cjs');
const root = path.resolve(__dirname,'../..');
const executable = process.env.DAF_DESKTOP_EXECUTABLE || path.join(root,'dist/m1.2-desktop',`DAF-${process.platform}-x64`,process.platform==='win32'?'DAF.exe':'DAF');
const resources = path.join(path.dirname(executable),'resources/planning');
const output = path.join(root,'desktop/test-output');
async function folder(){await fs.mkdir(output,{recursive:true});return fs.mkdtemp(path.join(output,'process-'));}
async function fixture(mode) {
  const base = await folder(), owned=path.join(base,'planning');
  await fs.cp(resources,owned,{recursive:true});
  if(mode==='slow') {
    const service=path.join(owned,'controller/service.py');
    await fs.appendFile(service,'\nimport time\n_original_perform = perform\ndef perform(request, folder):\n    (folder.parent / "child.pid").write_text(str(__import__("os").getpid()))\n    time.sleep(20)\n    return _original_perform(request, folder)\n');
  } else {
    await fs.writeFile(path.join(owned,'controller/entry.py'), mode==='extra'
      ? 'import sys\nsys.stdin.buffer.readline()\nsys.stdout.write("{}\\n{}\\n")\nsys.stdout.flush()\n'
      : 'import sys\nsys.stdin.buffer.readline()\nsys.stdout.buffer.write(b"x" * (1024*1024+1))\nsys.stdout.buffer.flush()\n');
  }
  return {base,owned,storage:path.join(base,'storage')};
}
async function waitFile(file){for(let i=0;i<100;i++){try{return await fs.readFile(file,'utf8');}catch{}await new Promise(r=>setTimeout(r,50));}throw new Error('Child did not start');}
test('bundled isolated runtime handles typed local history with no user Python',async()=>{
  const runner=new PlanningProcess(resources,path.join(await folder(),'history'));
  const result=await runner.run('planning.listImports');
  assert.equal(result.outcome,'listed',JSON.stringify(result));assert.deepEqual(result.imports,[]);assert.equal(runner.active,null);
});
test('fixed process rejects invalid output and oversized streams',async()=>{
  for(const mode of ['extra','large']) {
    const x=await fixture(mode);const runner=new PlanningProcess(x.owned,x.storage);
    const result=await runner.run('planning.listImports');assert.equal(result.error.code,'invalid_response');assert.equal(runner.active,null);
  }
});
test('cancel waits for owned child exit and refuses concurrent operations',async()=>{
  const x=await fixture('slow'),runner=new PlanningProcess(x.owned,x.storage);
  const pending=runner.run('planning.listImports'); await waitFile(path.join(x.base,'child.pid'));
  assert.equal((await runner.run('planning.listImports')).error.code,'busy');
  const child=runner.active.child; await runner.cancel();
  assert.equal((await pending).error.code,'cancelled_check_history');assert.equal(runner.active,null);
  assert.ok(child.exitCode!==null||child.signalCode!==null);assert.equal((await fs.readdir(x.base)).includes('storage'),false);
});
test('actual entry watchdog exits when its Node parent dies',async()=>{
  const x=await fixture('slow');
  const wrapper=path.join(x.base,'parent.cjs');
  await fs.writeFile(wrapper,`const {PlanningProcess}=require(${JSON.stringify(path.join(root,'desktop/planning-process.cjs'))});new PlanningProcess(${JSON.stringify(x.owned)},${JSON.stringify(x.storage)}).run('planning.listImports');`);
  const parent=spawn(process.execPath,[wrapper],{stdio:'ignore',windowsHide:true});
  try {
    const pid=Number(await waitFile(path.join(x.base,'child.pid')));
    parent.kill('SIGKILL'); await new Promise(resolve=>parent.once('close',resolve));
    let alive=true;
    for(let i=0;i<60;i++){try{process.kill(pid,0);}catch{alive=false;break;}await new Promise(r=>setTimeout(r,50));}
    assert.equal(alive,false,'Python child survived parent death');
  } finally {parent.kill('SIGKILL');}
});

test('observed Python network is bounded GitHub GET only; reopening is offline', {timeout:60000,skip:process.env.DAF_TEST_PUBLIC_READ!=='1'},async()=>{
  const base=await folder(),owned=path.join(base,'planning'),storage=path.join(base,'storage');
  await fs.cp(resources,owned,{recursive:true});
  // Test observer only: package code/transport is unchanged, no fake successful reader.
  await fs.appendFile(path.join(owned,'controller/service.py'),`\nimport sys\n_audit_file = Path(sys.argv[1] + '-audit.jsonl')\ndef _observe(event, args):\n    value = None\n    if event == 'socket.getaddrinfo': value = {'event':event,'host':args[0],'port':args[1]}\n    elif event == 'socket.connect': value = {'event':event,'port':args[1][1]}\n    elif event in ('socket.bind','subprocess.Popen','os.system'): value = {'event':event}\n    elif event == 'http.client.send':\n        raw = args[1]\n        value = {'event':event,'request':raw.split(b'\\r\\n',1)[0].decode('ascii'),'auth':b'authorization:' in raw.lower() or b'cookie:' in raw.lower()}\n    if value is not None:\n        with _audit_file.open('a',encoding='utf-8') as stream: stream.write(json.dumps(value)+'\\n')\nsys.addaudithook(_observe)\n`);
  const runner=new PlanningProcess(owned,storage);
  assert.equal((await runner.run('planning.listImports')).outcome,'listed');
  await assert.rejects(fs.readFile(storage+'-audit.jsonl'),{code:'ENOENT'});
  const source=require('../acceptance-source.json');
  const imported=await runner.run('planning.importPublicPlan',{source});assert.equal(imported.outcome,'imported',JSON.stringify(imported.error));
  const before=await fs.readFile(storage+'-audit.jsonl','utf8');const events=before.trim().split('\n').map(JSON.parse);
  const requests=events.filter(x=>x.event==='http.client.send');
  assert.equal(requests.length,source.path.split('/').length+2);assert.ok(requests.length<=18);
  for(const event of events) {
    if(event.event==='socket.getaddrinfo'){assert.equal(event.host,'api.github.com');assert.equal(event.port,443);}
    else if(event.event==='socket.connect')assert.equal(event.port,443);
    else if(event.event==='http.client.send'){assert.match(event.request,/^GET \/repos\/samuelwhite\/development-autonomy-framework\/(git\/(commits|trees)\/[a-f0-9]{40}|contents\/[A-Za-z0-9_./-]+\?ref=[a-f0-9]{40}) HTTP\/1\.1$/);assert.equal(event.auth,false);}
    else assert.fail('Unexpected network/server/command event: '+event.event);
  }
  assert.equal((await runner.run('planning.getImport',{id:imported.snapshot.id})).outcome,'loaded');
  assert.equal((await runner.run('planning.listImports')).outcome,'listed');
  assert.equal(await fs.readFile(storage+'-audit.jsonl','utf8'),before);
  await fs.writeFile(path.join(output,'python-network-summary.json'),JSON.stringify({publicRequests:requests.length,host:'api.github.com',port:443,methods:['GET'],authorizationHeaders:0,listeners:0,commands:0,offlineReopen:true,observer:'CPython audit hooks in isolated test copy'},null,2));
});

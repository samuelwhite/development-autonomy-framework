'use strict';
const { spawn } = require('node:child_process');
const path = require('node:path');
const { randomBytes } = require('node:crypto');
const contract = require('./planning-contract.cjs');
const refused = (requestId, code) => ({protocol:1,requestId,outcome:'refused',error:{code}});

class PlanningProcess {
  constructor(resources, storage) { this.resources = resources; this.storage = storage; this.active = null; }
  run(operation, data = {}) {
    const request = {protocol:1, requestId:randomBytes(16).toString('hex'), operation, ...data};
    contract.validate(request, contract.schema.$defs.request);
    if (request.source) contract.source(request.source);
    if (this.active) return Promise.resolve(refused(request.requestId, 'busy'));
    const input = JSON.stringify(request) + '\n';
    if (Buffer.byteLength(input) > 4096) return Promise.resolve(refused(request.requestId, 'invalid_request'));
    return new Promise(resolve => {
      const executable = path.join(this.resources, 'runtime', process.platform === 'win32' ? 'python.exe' : 'bin/python3.14');
      const env = { LANG:'C.UTF-8' };
      if (process.platform === 'win32') env.SystemRoot = process.env.SystemRoot;
      const child = spawn(executable, ['-I','-S','-B','-u',path.join(this.resources,'controller/entry.py'),this.storage], {
        shell:false, windowsHide:true, detached:false, cwd:this.resources, env, stdio:['pipe','pipe','pipe'],
      });
      const active = { child, cancelled:false, failure:null, requestId:request.requestId, done:null };
      this.active = active;
      let output = [], size = 0, stderr = 0;
      active.done = new Promise(done => { active.complete = done; });
      const stop = code => { active.failure ||= code; child.kill('SIGKILL'); };
      const deadline = setTimeout(() => stop('github_timeout'), 35000);
      child.stdout.on('data', chunk => { size += chunk.length; if(size > 1024*1024) stop('invalid_response'); else output.push(chunk); });
      child.stderr.on('data', chunk => { stderr += chunk.length; if(stderr > 8192) stop('invalid_response'); });
      child.on('error', () => { active.failure = 'runtime_unavailable'; });
      child.stdin.on('error', () => { /* close handles a crashed child; never retry */ });
      child.on('close', code => {
        clearTimeout(deadline);
        if (this.active === active) this.active = null;
        let result;
        try {
          if(active.cancelled) result = refused(request.requestId, 'cancelled_check_history');
          else if(active.failure || code !== 0) result = refused(request.requestId, active.failure || (code===124 ? 'github_timeout' : 'runtime_unavailable'));
          else {
            const raw = Buffer.concat(output);
            // Exactly one newline-terminated response; embedded newlines must be escaped JSON.
            if(raw.at(-1)!==10 || raw.subarray(0,-1).includes(10)) throw new Error('framing');
            result = contract.response(contract.strictJSON(raw), request);
          }
        } catch { result = refused(request.requestId, 'invalid_response'); }
        active.complete(); resolve(result);
      });
      child.stdin.write(input); // Leave open: EOF is the child's parent-death signal.
    });
  }
  async cancel() {
    const active = this.active;
    if (!active) return;
    active.cancelled = true;
    active.child.kill('SIGKILL');
    await active.done;
  }
}
module.exports = { PlanningProcess, refused };

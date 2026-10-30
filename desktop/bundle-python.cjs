'use strict';
// Build-time only. No downloads, PATH lookup or extraction happen in the installed app.
const fs = require('node:fs/promises');
const path = require('node:path');
const {createHash} = require('node:crypto');
const {execFileSync} = require('node:child_process');
const manifest = require('./python-runtime.json');
const modules = ['__init__.py','contract.py','external_receipts.py','supervised_handoff.py','github_planning.py','planning_snapshot.py'];
async function bundlePython(platform, destination) {
  const root = path.resolve(__dirname,'..'); const pin = manifest[platform];
  const cache = path.join(root,'dist/runtime-cache'); await fs.mkdir(cache,{recursive:true});
  const archive = path.join(cache,pin.archive);
  let bytes;
  try {bytes = await fs.readFile(archive);} catch(error) {if(error.code!=='ENOENT')throw error;}
  if(!bytes) {
    const response = await fetch(pin.url,{signal:AbortSignal.timeout(120000)});
    if(!response.ok) throw new Error('Python runtime download failed');
    bytes = Buffer.from(await response.arrayBuffer());
    if(bytes.length>100*1024*1024) throw new Error('Unexpected Python archive size');
  }
  if(createHash('sha256').update(bytes).digest('hex')!==pin.sha256) throw new Error('Python runtime checksum mismatch');
  await fs.writeFile(archive,bytes);
  const extracted = await fs.mkdtemp(path.join(cache,`extract-${platform}-`));
  execFileSync('tar',['-xf',archive,'-C',extracted],{windowsHide:true,stdio:'inherit'});
  const runtime = path.join(destination,'runtime'); await fs.mkdir(runtime,{recursive:true});
  if(platform==='win32') {
    await fs.cp(extracted,runtime,{recursive:true});
    await fs.writeFile(path.join(runtime,'python314._pth'),'python314.zip\n.\n');
    await fs.copyFile(path.join(runtime,'LICENSE.txt'),path.join(destination,'PYTHON-LICENSE.txt'));
  } else {
    const input=path.join(extracted,'python');
    await fs.mkdir(path.join(runtime,'bin'),{recursive:true});
    await fs.copyFile(path.join(input,'bin/python3.14'),path.join(runtime,'bin/python3.14'));
    await fs.chmod(path.join(runtime,'bin/python3.14'),0o755);
    await fs.cp(path.join(input,'lib'),path.join(runtime,'lib'),{recursive:true,filter:source=>{
      const parts=path.relative(input,source).split(path.sep);
      return !parts.some(p=>['site-packages','ensurepip','idlelib','tkinter','test','__pycache__'].includes(p))&&!source.endsWith('.a');
    }});
    await fs.copyFile(path.join(input,'lib/python3.14/LICENSE.txt'),path.join(destination,'PYTHON-LICENSE.txt'));
  }
  const controller=path.join(destination,'controller'); await fs.mkdir(path.join(controller,'daf'),{recursive:true});
  for(const file of ['entry.py','service.py']) await fs.copyFile(path.join(__dirname,'controller',file),path.join(controller,file));
  for(const file of modules) await fs.copyFile(path.join(root,'src/daf',file),path.join(controller,'daf',file));
  await fs.copyFile(path.join(__dirname,'planning-protocol.json'),path.join(destination,'planning-protocol.json'));
  await fs.copyFile(path.join(__dirname,'python-runtime.json'),path.join(destination,'python-runtime.json'));
  await fs.copyFile(path.join(__dirname,'PYTHON-NOTICES.txt'),path.join(destination,'PYTHON-NOTICES.txt'));
  await fs.cp(path.join(__dirname,'third-party'),path.join(destination,'third-party'),{recursive:true});
  return {version:manifest.version,...pin,modules};
}
module.exports={bundlePython,modules};

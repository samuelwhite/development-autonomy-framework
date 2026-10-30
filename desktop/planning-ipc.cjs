'use strict';
const {randomBytes} = require('node:crypto');
const {source, validate, schema} = require('./planning-contract.cjs');
const {refused} = require('./planning-process.cjs');
const planningURL = 'daf://app/planning.html';
const isPlanningURL = url => typeof url === 'string' && url.split('#')[0] === planningURL;
function validSender(event, win) {
  return !!win && !win.isDestroyed() && event.sender === win.webContents &&
    event.senderFrame === win.webContents.mainFrame && isPlanningURL(event.senderFrame.url) &&
    isPlanningURL(win.webContents.getURL());
}
function installPlanningIPC({ipcMain, dialog, win, runner}) {
  let approval = null, epoch = 0;
  const denied = code => refused(randomBytes(16).toString('hex'), code);
  const handler = (name, callback) => ipcMain.handle(name, async (event, ...args) => {
    if (!validSender(event, win)) return denied('invalid_request');
    try { return await callback(...args); } catch { return denied('invalid_request'); }
  });
  handler('planning:import', async (...args) => {
    if (args.length !== 1) return denied('invalid_request');
    const selected = {...source(args[0])};
    if (approval || runner.active) return denied('busy');
    const generation = epoch, consent = new AbortController(); approval = consent;
    let answer;
    try {
      answer = await dialog.showMessageBox(win, {type:'question',title:'Read this public GitHub plan?',
        message:'Allow this one public GitHub read?',
        detail:`Repository: ${selected.repository}\nCommit: ${selected.commit_sha}\nFile: ${selected.path}\n\nDAF will make bounded HTTPS GET requests to api.github.com to read this pinned file and its Git tree. It will save a local snapshot. No sign-in, repository changes, AI providers, execution or spending.`,
        buttons:['Cancel','Read plan'],defaultId:0,cancelId:0,noLink:true,signal:consent.signal});
    } finally { if(approval === consent) approval = null; }
    if (answer.response !== 1 || epoch !== generation || win.isDestroyed() || !isPlanningURL(win.webContents.getURL())) return denied('read_not_approved');
    return runner.run('planning.importPublicPlan', {source:selected});
  });
  handler('planning:list', (...args) => {
    if(args.length || approval) return denied(args.length ? 'invalid_request' : 'busy');
    return runner.run('planning.listImports');
  });
  handler('planning:get', (...args) => {
    if(args.length !== 1 || approval) return denied(args.length !== 1 ? 'invalid_request' : 'busy');
    validate(args[0], schema.$defs.snapshot.properties.id);
    return runner.run('planning.getImport', {id:args[0]});
  });
  const cancel = async () => { epoch++; approval?.abort(); approval = null; await runner.cancel(); };
  handler('planning:cancel', async (...args) => { if(args.length) return denied('invalid_request'); await cancel(); });
  return cancel;
}
module.exports = {installPlanningIPC, validSender, planningURL};

'use strict';
(() => {
  const api = window.dafPlanning;
  const $ = id => document.getElementById(id);
  let selected = null, busy = false;
  const errors = {
    invalid_request:'This request is not supported. Close and reopen DAF, then review the source again.',
    invalid_plan:'This file is not a complete, permitted DAF schema-1 plan. Ask its maintainer to check every milestone, task, dependency and protected path. Markdown is not supported.',
    invalid_source:'Use a public GitHub repository, a full lowercase 40-character commit and a portable relative .json path. Branches, tags, query strings, encoded paths and traversal are not supported.',
    github_unavailable:'GitHub could not be reached. Check your connection and try again when ready. Nothing will retry automatically.',
    github_not_found:'That public file or commit was not found. Check the repository, exact commit and path. Private repositories and sign-in are not supported.',
    github_rate_limited:'GitHub refused or rate-limited this public read. Wait and try again explicitly. DAF will not ask for a token.',
    github_tls_failed:'The secure connection to GitHub could not be verified. Check your system clock and trusted network. Do not disable certificate checks.',
    github_timeout:'The import took too long and was stopped. Check local history before trying again; a complete snapshot may have been saved just before it stopped.',
    github_response_refused:'GitHub returned an unsupported or oversized source/tree. Ask the maintainer for a small regular JSON plan in a smaller directory. Links and submodules are refused.',
    storage_unavailable:'DAF cannot safely access its local planning folder. Close DAF and check the local profile folder permissions and available disk space. Network drives and linked folders are unsupported.',
    storage_limit:'Local planning history is full (100 snapshots / 32 MiB). Close DAF and follow START-HERE.txt to archive or remove unwanted local snapshots. DAF will not delete evidence automatically.',
    snapshot_conflict:'A different or damaged record already has this source identity. DAF kept the original. Close DAF and follow START-HERE.txt to preserve and remove the conflicting local file before retrying.',
    corrupted_snapshot:'This saved snapshot failed complete-source validation. It will not be displayed as a valid plan. Close DAF, preserve the damaged file and follow START-HERE.txt before importing again.',
    runtime_unavailable:'The bundled planning runtime could not complete the request. Close DAF and re-extract the whole application into a new folder. Your saved snapshots remain in the profile folder.',
    invalid_response:'The planning runtime returned an invalid response. Close DAF and re-extract the complete application. Do not treat this result as verified.',
    busy:'Another local planning operation is still finishing. Wait or cancel the active import, then try again.',
    cancelled_check_history:'Import cancelled. No process remains active. Check local history: a complete snapshot may have been saved just before cancellation. No automatic retry will occur.',
    read_not_approved:'The GitHub read was not approved. No source was fetched.',
  };
  function node(tag, text, className) { const element=document.createElement(tag); if(text!==undefined) element.textContent=text; if(className) element.className=className; return element; }
  function message(text, error=false) { $('planning-message').textContent=text; $('planning-message').setAttribute('role',error?'alert':'status'); }
  function pairs(target, values) { for(const [name,value] of values) target.append(node('dt',name),node('dd',value)); }
  function setBusy(value, local=false) { busy=value; $('progress-text').textContent=local?'Revalidating the complete saved source on this device. No GitHub request is made.':'Waiting for permission, then reading the pinned source and validating the complete plan… Up to 30 seconds.'; for(const id of ['review-source','import-plan','refresh-history','source-link','repository','commit','plan-path']) $(id).disabled=value; $('import-progress').hidden=!value; for(const button of $('history-items').querySelectorAll('button')) button.disabled=value; }
  function source() {
    const link=$('source-link').value.trim(); let result;
    if(link) {
      const match=/^https:\/\/github\.com\/([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)\/blob\/([a-f0-9]{40})\/([A-Za-z0-9_./-]+\.json)$/.exec(link);
      if(!match) throw new Error('invalid_source'); result={repository:match[1],commit_sha:match[2],path:match[3]};
    } else result={repository:$('repository').value.trim(),commit_sha:$('commit').value.trim(),path:$('plan-path').value.trim()};
    if(!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(result.repository)||!(/^[a-f0-9]{40}$/).test(result.commit_sha)||!(/^[A-Za-z0-9_./-]+\.json$/).test(result.path)||result.path.length>240||result.path.split('/').length>16) throw new Error('invalid_source');
    for(const part of result.path.split('/')) if(!part||['.','..','.git'].includes(part.toLowerCase())||part.endsWith('.')||/^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)/i.test(part)) throw new Error('invalid_source');
    return result;
  }
  function showError(result) { message(errors[result?.error?.code] || errors.invalid_response,true); }
  function render(view) {
    const area=$('plan-view'); area.replaceChildren(); area.hidden=false;
    const intro=node('section',undefined,'panel');
    const title=node('h2',`${view.project} · ${view.planId}`); title.id='plan-heading'; title.tabIndex=-1;
    intro.append(node('p','VALIDATED PLANNING STRUCTURE · SOURCE CLAIMS UNVERIFIED','eyebrow'),title,node('p','Proposed — not approved or executed','proposed'));
    intro.append(node('p','This local snapshot passed complete-plan validation. Its source requirements and stored provenance are not authenticated approvals or evidence that work happened.'));
    const provenance=node('dl'); pairs(provenance,[['Repository',view.source.repository],['Source commit',view.source.commit_sha],['Plan file',view.source.path],['Git blob',view.source.git_blob_sha],['Source SHA-256',view.source.content_sha256],['Plan SHA-256',view.source.plan_sha256],['Snapshot ID',view.id],['Plan version',String(view.version)],['Declared baseline',view.baseline]]);
    intro.append(provenance,node('p','The source commit pins the file DAF read. The declared baseline describes the plan’s intended starting point; DAF has not checked that it is current.','subnote'));
    for(const [heading,items] of [['Scope',view.scope],['Deliverables',view.deliverables]]) {intro.append(node('h3',heading)); const list=node('ul'); items.forEach(item=>list.append(node('li',item,'source-text'))); intro.append(list);}
    area.append(intro);
    for(const milestone of view.milestones) {
      const panel=node('article',undefined,'panel proposal');
      panel.append(node('p',`MILESTONE ${milestone.id}`,'eyebrow'),node('h3',milestone.deliverable),node('p','Proposed — not approved or executed','proposed'),node('p',`Depends on: ${milestone.dependencies.join(', ')||'No earlier milestone'}`),node('p','Dependencies express ordering, not completed work.','subnote'),node('h4','Proposed task'),node('p',milestone.instruction,'source-text'),node('h4','Acceptance criteria'));
      const acceptance=node('dl'); pairs(acceptance,Object.entries(milestone.acceptance)); panel.append(acceptance,node('h4','Permitted paths in the source plan')); const paths=node('ul'); milestone.allowedPaths.forEach(p=>paths.append(node('li',p,'source-text'))); panel.append(paths);
      const details=node('details'); details.append(node('summary','Proposal identity and source-supplied checks')); const ids=node('dl'); pairs(ids,[['Proposal ID',milestone.proposalId],['Task SHA-256',milestone.taskSHA256]]); details.append(ids,node('pre',milestone.checks),node('p','Requirements only. No check was run or independently verified.')); panel.append(details); area.append(panel);
    }
    const requirements=node('details',undefined,'panel'); requirements.append(node('summary','Complete source boundaries and requirements'),node('p','These declared budgets, checks and recovery settings are source requirements. They grant no spending or execution authority.'),node('pre',view.requirements)); area.append(requirements); title.focus();
  }
  async function refresh(quiet=false) {
    if(!api) {message(errors.runtime_unavailable,true); return;}
    const result=await api.listImports(); if(result.outcome==='refused') {showError(result);return;}
    const area=$('history-items'); area.replaceChildren();
    if(!result.imports.length) area.append(node('p','No saved imports yet.'));
    for(const entry of result.imports) {
      const row=node('div',undefined,'import-entry'); const button=node('button',`${entry.project} · ${entry.planId}`,'secondary'); button.disabled=busy;
      button.addEventListener('click',async()=>{if(busy)return;setBusy(true,true);try{const result=await api.getImport(entry.id);if(result.snapshot){render(result.snapshot);message('Saved source revalidated locally. No GitHub request was made.');}else showError(result);}catch{message(errors.runtime_unavailable,true);}finally{setBusy(false);}});
      row.append(button,node('p',`${entry.source.repository} · ${entry.source.path}`,'source-text'),node('small',entry.source.commit_sha,'source-text')); area.append(row);
    }
    if(result.damaged.length) {area.append(node('p',`${result.damaged.length} saved record(s) refused as damaged. Preserve these files and follow START-HERE.txt; they are not shown as valid plans.`)); result.damaged.forEach(id=>area.append(node('code',`${id}.json`,'source-text')));}
    if(!quiet&&!result.damaged.length) message('Local history refreshed. No GitHub request was made.');
  }
  $('review-source').addEventListener('click',()=>{try{selected=source();$('source-summary').replaceChildren();pairs($('source-summary'),[['Repository',selected.repository],['Exact commit',selected.commit_sha],['File',selected.path]]);$('read-review').hidden=false;message('Review the exact source, then choose whether to allow the public read.');$('import-plan').focus();}catch{selected=null;$('read-review').hidden=true;message(errors.invalid_source,true);}});
  for(const id of ['source-link','repository','commit','plan-path']) $(id).addEventListener('input',()=>{selected=null;$('read-review').hidden=true;});
  $('import-plan').addEventListener('click',async()=>{if(busy||!selected)return;let saved=false;$('plan-view').hidden=true;setBusy(true);message('Waiting for your confirmation, then reading and validating the pinned source…');try{const result=await api.importPublicPlan(selected);if(result.snapshot){saved=true;render(result.snapshot);message(result.outcome==='already_present'?'This identical source was already saved. Its complete plan was revalidated; no duplicate was created.':'Imported and saved. All tasks remain proposals; no execution or spending is available.');}else showError(result);}catch{message(errors.runtime_unavailable,true);}finally{try{if(saved)await refresh(true);}finally{setBusy(false);}}});
  $('cancel-import').addEventListener('click',async()=>{await api.cancelImport();});
  $('refresh-history').addEventListener('click',()=>{if(!busy)void refresh();});
  void refresh(true).catch(()=>message(errors.runtime_unavailable,true));
})();

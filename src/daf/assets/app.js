"use strict";
const $ = id => document.getElementById(id);
const el = (tag, text, cls) => {const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(cls)n.className=cls; return n;};
const number = value => new Intl.NumberFormat("en").format(value);
const p=snapshot.progression;
for (const [value,label] of [[p.milestones.length,"Milestones accepted"],[p.jobs.length,"Attempts retained"],[number(p.known_actual_tokens),"Known fixture tokens"],["0","Real provider requests"]]) {
  const card=el("article",undefined,"metric"); card.append(el("strong",value),el("span",label)); $("metrics").append(card);
}
for (const [title,run,detail] of [["Progression",p,"One failed attempt corrected; restart reconciled without duplicate work."],["Scope boundary",snapshot.scope_blocker,"A proposed permission change requires an owner decision."],["Emergency stop",snapshot.stopped,"Stop committed before admission. No job was dispatched."]]) {
  const card=el("article",undefined,"project"); card.append(el("span",run.run.status.replaceAll("_"," "),"status "+run.run.status),el("h3",title),el("p",detail),el("small",`Merge: ${snapshot.merge} · Deployment: ${snapshot.deployment}`)); $("portfolio").append(card);
}
for(const task of p.tasks){const card=el("article",undefined,"milestone"); card.append(el("span",task.id,"step"),el("h3",task.deliverable),el("p",Object.values(task.acceptance).join(" ")),el("small",`Depends on: ${task.depends_on.join(", ")||"none"}`),el("span","Accepted in fixture","status completed")); $("milestones").append(card);}
for(const attempt of p.attempts){const row=el("tr");for(const value of [attempt.milestone,attempt.attempt,attempt.status,Object.entries(attempt.checks).map(([k,v])=>`${k}: ${v}`).join(" · "),attempt.actual_tokens===null?"Unknown":number(attempt.actual_tokens)])row.append(el("td",value));if(attempt.status==="failed")row.className="failure";$("attempts").append(row);}
const b=snapshot.bounded;
for(const line of [`${b.simulated_sends} once-only simulated sends`,`${number(b.known_gross_tokens)} known fixture tokens / ${number(b.reserved_tokens)} reserved`,"Third segment blocked by its budget","Live transport: unproven and unavailable"]){$("bounded").append(el("p",line,"detail"));}
for(const line of [snapshot.planning,snapshot.ci,"Execution authority: none","Notification delivery: disabled","Scope blocker: unresolved in its own scenario"]){$("decisions").append(el("p",line,"detail"));}

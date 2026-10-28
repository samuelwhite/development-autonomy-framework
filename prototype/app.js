(function () {
  "use strict";
  const sim = window.DAFSimulation;
  const key = "daf-v02-offline-prototype";
  let state = sim.initial();
  let storageAvailable = true;
  try { state = sim.restore(sessionStorage.getItem(key)); } catch { storageAvailable = false; }
  let timer;
  const content = document.getElementById("content");
  const nav = document.getElementById("steps");
  const openDetails = new Map();
  const names = { overview: "Overview", results: "Results", activity: "Activity", settings: "Settings" };
  const setupNames = ["Welcome", "Your assistant", "Your project", "How we work", "First task"];
  const setupIndex = () => [0, 1, 1, 2, 3, 3, 4][state.step];
  const escape = value => String(value).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const button = (label, action, type = "primary", disabled = false, attrs = "") =>
    `<button class="${type}" data-action="${action}" data-focus="${action}" ${disabled ? "disabled" : ""} ${attrs}>${label}</button>`;
  const intro = (title, body) => `<p class="eyebrow">GETTING STARTED · ${setupIndex()} OF 4</p><h1>${title}</h1><p class="lead">${body}</p>`;
  const backNext = (disabled = false) => `<div class="actions">${button("← Back", "back", "text-button")}${button("Continue →", "next", "primary", disabled)}</div>`;
  const provider = () => sim.providers[state.provider];
  const permission = () => state.mode === "review" ? "Suggestions only" : "Ask before any changes";
  const busy = () => [...sim.active, "uncertain"].includes(state.status);
  const needsAttention = () => ["awaiting_approval", "uncertain", "failed", "limited"].includes(state.status);
  const disclosure = (id, title, body) => `<details data-disclosure="${id}"><summary data-focus="disclosure-${id}">${title}</summary>${body}</details>`;
  function choice(field, value, title, body, extra = "") {
    return `<label class="choice ${state[field] === value ? "selected" : ""}">
      <input type="radio" name="${field}" value="${value}" data-focus="${field}-${value}" ${state[field] === value ? "checked" : ""}>
      ${extra}<h2>${title}</h2><p>${body}</p></label>`;
  }
  function welcome() {
    return `<p class="eyebrow">A LITTLE HELP. A CLEAR WAY FORWARD.</p>
      <div class="hero"><div><h1>Your next idea.<br><em>Within reach.</em></h1>
      <p class="lead">DAF helps you improve a software project with an AI assistant. Choose what you want to achieve, decide what it can do, and see your progress in one place.</p>
      ${button("Let’s get started →", "next")}<p class="subnote">Try an example in a few minutes. No account needed.</p></div>
      <div class="preview-card" aria-label="Example of project progress"><div class="mini-top"><strong>Your project, at a glance</strong><span class="pill">EXAMPLE</span></div>
      <h2>A friendlier first step</h2><p class="subnote">Helping someone get started with your project</p>
      <div class="mini-row"><span class="check">✓</span> Understand the project</div>
      <div class="mini-row"><span class="check">✓</span> Suggest an improvement</div>
      <div class="mini-row"><span class="check">○</span> Your result, ready to review</div>
      <div class="mini-foot"><span>You choose what’s allowed.</span><span>Stop at any time.</span></div></div></div>
      <div class="features"><div><div class="feature-number">01 / CHOOSE</div><h3>Start with something small</h3><p>Pick an example project and a useful first task.</p></div>
      <div><div class="feature-number">02 / DECIDE</div><h3>You stay in control</h3><p>Get suggestions, or ask to approve changes first.</p></div>
      <div><div class="feature-number">03 / FOLLOW ALONG</div><h3>Know what happens next</h3><p>See progress, results and anything that needs you.</p></div></div>`;
  }
  function chooseProvider() {
    return intro("Choose your AI assistant", "Your assistant helps DAF understand a project and work on your task. Choose the one you’d like to try.") +
      `<fieldset><legend class="sr-only">AI assistant</legend><div class="cards">
      ${choice("provider", "codex", "OpenAI Codex", "OpenAI’s coding assistant. A future connection could use an eligible ChatGPT account or a separately billed developer account.", '<span class="symbol" aria-hidden="true">◎</span>')}
      ${choice("provider", "claude", "Claude Code", "Anthropic’s coding assistant. DAF’s proposed connection needs a separately billed developer account; a Claude subscription alone would not cover it.", '<span class="symbol" aria-hidden="true">✳</span>')}
      </div></fieldset><p class="subnote">Both can explain a project, suggest improvements and help prepare changes. This demo is free whichever you choose.</p>
      ${!state.provider ? '<p class="selection-hint">Choose an assistant to continue.</p>' : ""}` + backNext(!state.provider);
  }
  function connect() {
    const codex = state.provider === "codex";
    return intro(`Let’s get ${provider().name} ready`, "This is where you’d connect your assistant to DAF. Today, you can try that step without signing in.") +
      `<section class="panel connection-card"><span class="symbol" aria-hidden="true">${codex ? "◎" : "✳"}</span>
      <h2>${codex ? "Your OpenAI account" : "Your Anthropic developer account"}</h2>
      <p>${codex ? "With a real connection, OpenAI would guide you through sign-in in your browser. You’d then return here to choose a project." : "With a real connection, we’d guide you through linking your developer account. Its usage is billed separately from a Claude subscription."}</p>
      <p><strong>For now, we’ll use a demo connection.</strong> There’s no account to link and nothing to pay.</p>
      ${button("Try the demo connection →", "connect")}</section>
      <div class="actions">${button("← Choose another assistant", "back", "text-button")}</div>`;
  }
  function projects() {
    return intro("What would you like to explore?", "Try an example project to see how DAF helps. Everything here is made up for the demo.") +
      `<h2 class="section-label">Try an example project</h2><fieldset><legend class="sr-only">Example project</legend><div class="cards">
      ${choice("project", "Fieldnotes", "Fieldnotes", "Imagine a small app for saving notes and ideas. Help a new user understand how to create their first note.", '<span class="symbol" aria-hidden="true">▤</span><span class="pill">EXAMPLE NOTES APP</span>')}
      ${choice("project", "Little Library", "Little Library", "Imagine an app for organising your books. Help someone add their first book and explore their collection.", '<span class="symbol" aria-hidden="true">▥</span><span class="pill">EXAMPLE BOOK APP</span>')}
      </div></fieldset><div class="future-project"><div><h2>Use my own project</h2><p>In a future version, you’ll choose a project from your computer. This demo cannot open your files.</p></div><span class="pill muted">COMING LATER</span></div>` + backNext();
  }
  function boundaries() {
    return intro("How would you like DAF to help?", "Start with suggestions, or try approving a change before it happens. You can stop the task at any time.") +
      `<fieldset><legend class="sr-only">What DAF is allowed to do</legend><div class="cards permission-cards">
      ${choice("mode", "review", "Just give me suggestions", "DAF can look at the example and recommend improvements, but cannot change anything. For example: suggest a clearer introduction.", '<span class="pill">A GOOD PLACE TO START</span>')}
      ${choice("mode", "edit", "Make changes, but ask me first", "DAF can propose a change and show it to you. It must get your permission before applying it to the example.")}
      </div></fieldset><div class="plain-limits"><div><strong>One small task</strong><span>Up to ${state.minutes} minutes. No automatic retries.</span></div><div><strong>Free to try</strong><span>$0 real spending. Paid requests are unavailable.</span></div></div>
      <p class="subnote">DAF cannot access your other files, publish work or put a project live. A future real connection must explain its costs before you start.</p>
      <div class="panel advanced">${disclosure("limits", "More about permissions and limits", `
      <div class="form-row"><label class="field">Time limit<select name="minutes" data-focus="minutes"><option value="5" ${state.minutes === 5 ? "selected" : ""}>5 minutes</option><option value="10" ${state.minutes === 10 ? "selected" : ""}>10 minutes</option></select><small>Includes time spent waiting for your approval. A hidden or closed page cannot enforce a background timer.</small></label>
      <label class="field">Demo workload limit<select name="tokens" data-focus="tokens"><option value="1000" ${state.tokens === 1000 ? "selected" : ""}>1,000 example tokens</option><option value="2000" ${state.tokens === 2000 ? "selected" : ""}>2,000 example tokens</option></select><small>Tokens are small pieces of text an AI works with. This task sets aside 800 simulated tokens, not money.</small></label></div>
      <ul class="plain-list"><li>Only the chosen example project is in scope.</li><li>Shell commands and tool internet access are blocked.</li><li>Merging and deployment are blocked. One task, no automatic retries.</li><li>Real spending limits would need to be proven before paid work is allowed.</li></ul>`)}</div>
      <div class="demo-options">${disclosure("setup-demo", "Explore a setup problem (optional demo)", `<label class="field">Try an automatic check that needs attention<select name="setupIssue" data-focus="setupIssue"><option value="none" ${state.setupIssue === "none" ? "selected" : ""}>Everything is ready</option><option value="connection" ${state.setupIssue === "connection" ? "selected" : ""}>Assistant connection unavailable</option><option value="permissions" ${state.setupIssue === "permissions" ? "selected" : ""}>Permission check fails</option><option value="limits" ${state.setupIssue === "limits" ? "selected" : ""}>Task limits cannot be confirmed</option></select></label>`)}</div>` + backNext();
  }
  const checkProblems = {
    connection: { title: "We couldn’t confirm the assistant connection", why: "DAF needs a working connection before it can start your task.", fix: "Reconnect the demo assistant, then we’ll check again.", button: "Fix this: reconnect the demo", help: "This example mimics an interrupted sign-in. A real connection would need you to finish sign-in with the provider. Retry checks the same connection; it does not skip this check." },
    permissions: { title: "We couldn’t confirm the selected permissions", why: "DAF must know exactly what it is allowed to do before starting.", fix: "Switch to suggestions only and check again. This removes permission to make changes.", button: "Fix this: use suggestions only", help: "The demo is showing a permission mismatch. The fix chooses the safest option and runs the check again. If you need different permissions later, return to How we work and review them explicitly." },
    limits: { title: "We couldn’t confirm the task limits", why: "DAF won’t start without a clear limit on how much work it can do.", fix: "Restore the recommended limits: five minutes and 1,000 example tokens. Then we’ll check again.", button: "Fix this: restore recommended limits", help: "This is a demo of an unreadable limit. Restoring the defaults does not enable paid requests or increase the allowance. Retry alone leaves the problem in place." }
  };
  function verification() {
    if (state.checkStatus !== "failed") return intro("Getting everything ready…", "We’re checking the assistant, your permissions and the task limits. You don’t need to do anything.") +
      `<div class="panel checking" aria-busy="true"><span class="checking-dot" aria-hidden="true"></span><h2>Checking your demo setup</h2><p>You’ll go straight to your first task when everything is ready.</p></div><div class="actions">${button("← Back", "back", "text-button")}</div>`;
    const problem = checkProblems[state.checkError];
    return intro("One thing needs your attention", "Your task hasn’t started. We’ll keep it on hold until this check passes.") +
      `<section class="panel attention" role="alert"><p class="eyebrow">SETUP CHECK</p><h2>${problem.title}</h2>
      <p>${problem.why}</p><p><strong>What to do:</strong> ${problem.fix}</p><div class="compact">${button(problem.button, "fix-check")}${button("Retry", "retry-check", "secondary")}</div>
      ${disclosure("check-help", "Help with this check", `<p>${problem.help}</p>`)}</section><div class="actions">${button("← Review my settings", "back", "text-button")}</div>`;
  }
  function scenarioOptions() {
    return `<label class="field">What should happen during this demo task?<select name="scenario" data-focus="scenario" ${state.status !== "ready" ? "disabled" : ""}>
      <option value="normal" ${state.scenario === "normal" ? "selected" : ""}>Normal progress</option>
      <option value="check-failure" ${state.scenario === "check-failure" ? "selected" : ""}>Result does not pass its check</option>
      <option value="limit" ${state.scenario === "limit" ? "selected" : ""}>Next step would exceed the allowance</option>
      <option value="connection-lost" ${state.scenario === "connection-lost" ? "selected" : ""}>Connection is lost</option></select></label>`;
  }
  function firstTask() {
    return intro("Start with a useful little task", "Choose a starting point. There’s no need to write instructions — we’ve prepared an example for you.") +
      `<p class="ready-note"><span class="check">✓</span> Your demo connection, permissions and limits are ready.</p>
      <fieldset><legend class="sr-only">Starter task</legend><div class="starter-tasks">
      ${Object.entries(sim.tasks).map(([id, task]) => choice("taskKind", id, task.title, task.outcome)).join("")}</div></fieldset>
      <div class="custom-task">${disclosure("custom-task", "Prefer to write your own task?", `${button("Use my own words", "custom", "secondary")}
      <label class="field" for="customTask">Your task<textarea id="customTask" name="customTask" data-focus="customTask" maxlength="500" ${state.taskKind !== "custom" ? "disabled" : ""} placeholder="Tell DAF what you’d like help with…">${escape(state.customTask)}</textarea></label>
      <p class="subnote">Your words stay in this tab. The demo will show a sample documentation task, not a response to your custom request.</p>`)}</div>
      <section class="panel next-preview"><h2>Here’s what will happen</h2><p><strong>${provider().name}</strong> will work through the <strong>${state.project}</strong> example and prepare ${state.taskKind === "plan" ? "a short plan" : state.taskKind === "review" ? "three suggestions" : "a clearer introduction"}.</p>
      <p>${sim.edits(state) ? "You’ll see the proposed change and choose whether to allow it. DAF then checks the result." : "You’ll get ideas to review. Nothing will be changed, and you won’t need to approve any edits."}</p>
      <div class="summary-line"><span>${permission()}</span><span>Up to ${state.minutes} minutes</span><span>$0 real cost</span></div>
      ${state.taskKind === "custom" ? '<p class="subnote">Selected: your own words, using the sample documentation demonstration.</p>' : ""}</section>
      <div class="demo-options">${disclosure("task-demo", "Explore a task problem (optional demo)", scenarioOptions())}</div>
      <div class="actions">${button("← Back", "back", "text-button")}${button("Start example task →", "begin")}</div><p id="task-error" class="error" role="alert"></p>`;
  }
  const statuses = { ready: "Ready to start", running: "Making progress", awaiting_approval: "Your permission is needed", validating: "Checking the result", completed: "Task complete", stopped: "Work stopped", failed: "Result needs attention", limited: "Task limit reached", uncertain: "Earlier work needs checking" };
  function activityText() {
    if (state.status === "running") return state.phase === 0 ? "Getting to know the example project" : "Preparing an improvement for you";
    if (state.status === "validating") return "Checking the result before marking it complete";
    if (state.status === "awaiting_approval") return "Waiting for your decision on one proposed change";
    if (state.status === "completed") return "Your result is ready. Nothing else is scheduled.";
    if (state.status === "uncertain") return "New work is on hold until the earlier task is checked";
    if (state.status === "failed") return "The result hasn’t passed its check. No retry is running.";
    if (state.status === "limited") return "Stopped before doing more than you allowed";
    return "Nothing is running or scheduled to restart";
  }
  function progress() {
    const milestones = sim.milestones(state);
    const done = milestones.filter(m => m.state === "done").length;
    const percent = Math.round(done / milestones.length * 100);
    return `<section class="panel project-progress"><div class="section-heading"><div><p class="eyebrow">FIRST TASK PROGRESS</p><h2>${escape(state.task)}</h2></div><strong class="progress-number">${percent}%</strong></div>
      <progress max="3" value="${done}" aria-label="Completed milestones">${done} of 3</progress>
      <p class="subnote">${done} of 3 milestones completed</p><div class="current-activity"><span class="local-dot"></span><strong>${activityText()}</strong></div>
      <ol class="milestones">${milestones.map(m => `<li class="${m.state}"><span class="milestone-mark" aria-hidden="true">${m.state === "done" ? "✓" : m.state === "current" ? "•" : "○"}</span><span>${m.label}</span><small>${m.state === "done" ? "Complete" : m.state === "current" ? (state.status === "awaiting_approval" ? "Waiting for you" : "In progress") : "Up next"}</small></li>`).join("")}</ol>
      <div class="up-next"><h3>${state.status === "completed" ? "What’s next?" : "Coming up"}</h3><p>${state.status === "completed" ? "Review your result and decide what you’d like to do next. This demo won’t start another task." : needsAttention() ? "Resolve the item below before work can continue. No extra task will start on its own." : state.status === "stopped" ? "Choose a fresh example in Settings when you are ready. Nothing will restart by itself." : "DAF will finish the remaining milestones and put the result here."}</p></div></section>`;
  }
  function attention() {
    if (state.status === "awaiting_approval") return `<section class="panel attention"><p class="eyebrow">ONE DECISION FOR YOU</p><h2>May DAF apply this example change?</h2><p>This replaces a vague instruction in ${state.project}’s example getting-started guide. Your permission covers this change only.</p>
      <div class="change-preview"><div><small>BEFORE</small><p>Start the app.</p></div><div><small>AFTER</small><h3>Getting started</h3><p>${sim.projects[state.project].firstStep}</p></div></div>
      <div class="compact">${button("Allow this example change", "allow", "primary", false, `data-approval="${state.approval}"`)}${button("No, stop here", "deny", "secondary", false, `data-approval="${state.approval}"`)}</div><p class="subnote">Only the example is affected. Other files, publishing and going live remain blocked.</p></section>`;
    if (state.status === "uncertain") return `<section class="panel attention" role="alert"><p class="eyebrow">CHECK BEFORE CONTINUING</p><h2>${state.recoveryFailed ? "We still couldn’t confirm what happened" : "Let’s check where the work stopped"}</h2>
      <p>${state.recoveryFailed ? "The example’s earlier result is still unavailable." : "The page was reloaded or the demo connection was interrupted, so we can’t yet confirm the last result."} Starting again could duplicate work. DAF has kept its allowance set aside.</p>
      <p><strong>What to do:</strong> ${state.recoveryFailed ? "Use the fix to make the demo result available, then check the original task again." : "Check the earlier work. This inspects the original task; it does not restart it."}</p>
      <div class="compact">${state.recoveryFailed ? button("Fix this: make the demo result available", "fix-recovery") + button("Retry", "reconcile", "secondary") : button("Check earlier work", "reconcile")}</div>
      ${disclosure("recovery-help", "Why does DAF need to check?", '<p>Stopping new work does not tell us what happened just before an interruption. The demo confirms the original task has stopped before releasing its allowance. It cannot recover a real connection or a deleted browser tab.</p>')}</section>`;
    if (state.status === "failed") return `<section class="panel attention" role="alert"><p class="eyebrow">QUALITY CHECK</p><h2>The example result isn’t ready yet</h2><p>${sim.edits(state) ? "The example change is missing a required getting-started heading." : "The example result is missing a required explanation of the first step."} DAF hasn’t marked the task complete because the result would be unclear to a new user.</p><p><strong>What to do:</strong> review the finding below. You can start a fresh demo from Settings if you’d like to try again; this task allows no automatic retries.</p>${button("Review the finding", "show-results", "secondary")}${disclosure("result-help", "Help with this result", '<p>A separate demo check disagreed with the assistant’s result. A real task would need a corrected result and another permitted check. DAF does not turn a failed check into a success or quietly increase your limits.</p>')}</section>`;
    if (state.status === "limited") return `<section class="panel attention" role="alert"><p class="eyebrow">YOUR LIMIT HELD</p><h2>The next step would use too much of your allowance</h2><p>The demo used 800 example tokens. Its next step needs 1,500, which is more than remains. DAF stopped before that step, so the task is incomplete.</p><p><strong>What to do:</strong> review your limits in Settings. To try a smaller task, start a fresh demo there. This task will not restart or increase its own limit.</p>${button("Review my limits", "show-settings", "secondary")}${disclosure("budget-help", "What is this allowance?", '<p>Tokens are pieces of text an AI works with. These numbers are made up for the demo and have no monetary value. Real paid work would need a separately verified spending limit.</p>')}</section>`;
    if (state.status === "stopped") return `<section class="panel stopped-note"><h2>${state.stopReason === "time" ? "Your time limit stopped the task" : "The task is stopped"}</h2><p>${state.stopReason === "recovered" ? "The earlier work was checked and confirmed stopped. No duplicate task was created." : state.stopReason === "denied" ? "You declined the change, so it was not applied." : "Nothing else will run, and any pending permission request has been cancelled."} Your progress remains here in this tab. Use Settings to start a fresh example when you’re ready.</p></section>`;
    return "";
  }
  function resultContent() {
    if (state.status === "failed") return '<p class="finding">Check failed: the result needs a clear getting-started heading and an explanation of the first step. This task has not been accepted.</p>';
    if (state.status !== "completed") return `<p class="empty-state">${state.status === "awaiting_approval" ? "A proposed change is waiting for your permission in Overview." : "Your finished result will appear here. You can follow the milestones in Overview."}</p>`;
    if (state.taskKind === "review") return `<ol class="result-list"><li><strong>Make the first step clear.</strong> Explain how someone starts using ${state.project}.</li><li><strong>Add an example.</strong> Show what a finished ${state.project === "Fieldnotes" ? "note" : "book entry"} looks like.</li><li><strong>Explain how to find things again.</strong> A short search tip will help returning users.</li></ol><p>Start with the first step — it’s a small improvement with a clear benefit.</p>`;
    if (state.taskKind === "plan") return `<ol class="result-list"><li>Choose what people should be able to search: ${state.project === "Fieldnotes" ? "note titles" : "book titles"} first.</li><li>Sketch a search box and a helpful message for no results.</li><li>Try the idea with a few example entries before building it.</li></ol><p>This is a suggested plan, not a queue of work. Nothing has been changed or scheduled.</p>`;
    return `<div class="result-document"><p class="eyebrow">${sim.edits(state) ? "APPROVED EXAMPLE CHANGE" : "SUGGESTED INTRODUCTION"}</p><h3>Getting started with ${state.project}</h3><p>${sim.projects[state.project].firstStep}</p></div><p class="subnote">${sim.edits(state) ? "You approved this one example change and its separate demo checks passed." : "This is a suggestion for you to review. Nothing was changed."}${state.taskKind === "custom" ? " This is the sample documentation result, not a response to your custom words." : ""}</p>`;
  }
  function history(all = false) {
    const events = all ? state.events : state.events.slice(-3);
    return `<ol class="timeline" aria-label="Recent activity">${events.map(e => `<li><small>STEP ${e.id}</small>${escape(e.text)}</li>`).join("")}</ol>`;
  }
  function resources() {
    return `<section class="panel resources"><h2>Usage and limits</h2><div class="resource-row"><span>Real spending</span><strong>$0.00</strong></div><p class="subnote">Free demo. Paid requests are unavailable.</p>
      <div class="resource-row"><span>Task time limit</span><strong>${state.minutes} minutes</strong></div><div class="resource-row"><span>Work at once</span><strong>One task</strong></div>
      <p class="usage-state">${state.status === "uncertain" ? "Allowance held while we check" : state.status === "limited" ? "Not enough allowance for the next step" : "Within your demo allowance"}</p>
      ${disclosure("usage", "See usage details", `<p>${state.used.toLocaleString()} of ${state.tokens.toLocaleString()} example tokens used; ${state.reserved.toLocaleString()} set aside for unfinished work.</p><p>All usage is simulated. Unknown work keeps its allowance until its outcome is confirmed. Time includes approval waits; hidden tabs may pause, and limits are checked again on return.</p>`)}</section>`;
  }
  function settings() {
    return `<section class="panel"><h2>Your choices</h2><dl class="details-list"><div><dt>ASSISTANT</dt><dd>${provider().name} · Demo connection</dd></div><div><dt>PROJECT</dt><dd>${state.project} · Example only</dd></div><div><dt>WHAT DAF MAY DO</dt><dd>${permission()}. ${state.mode === "review" ? "It cannot change anything." : "Each proposed edit needs your permission."}</dd></div><div><dt>WHAT DAF CANNOT DO</dt><dd>Access other files, run shell commands, use tool internet access, publish changes or put anything live.</dd></div><div><dt>LIMITS</dt><dd>${state.minutes} minutes · ${state.tokens.toLocaleString()} example tokens · One task · No automatic retries · $0 real cost</dd></div></dl></section>
      <section class="panel"><h2>Returning to your work</h2><p>This demo remembers progress in this tab when your browser allows it. Closing the tab may lose it. It does no background work and sends no notifications.</p><p>Reloading during a task asks you to check the earlier work. It never silently starts the task again.</p></section>
      <section class="panel">${disclosure("workspace-demo", "Explore demo problems", `${scenarioOptions()}<div class="compact">${button("Interrupt the demo connection", "disconnect", "secondary", !sim.active.includes(state.status))}${button("Reach the time limit", "time-limit", "secondary", !sim.active.includes(state.status))}</div>
      <label class="checkbox-label"><input type="checkbox" name="recoveryUnavailable" data-focus="recoveryUnavailable" ${state.recoveryUnavailable ? "checked" : ""} ${state.status !== "uncertain" ? "disabled" : ""}> Make the earlier result unavailable during the recovery demo</label>`)}</section>
      <section class="panel"><h2>Try a fresh example</h2><p>Start over to choose another assistant, project or task. This clears the progress and history for this demo only.</p>${button("Start over", "reset", "secondary", busy())}${busy() ? '<p class="subnote">Stop the current task first. If its outcome is unknown, check the earlier work before starting over.</p>' : ""}</section>`;
  }
  function dashboard() {
    const header = `<div class="dashboard-top"><div><p class="eyebrow">${state.project.toUpperCase()} · EXAMPLE PROJECT</p><h1>${state.view === "overview" ? "Mission Control" : names[state.view]}</h1><p class="lead">${state.view === "overview" ? sim.projects[state.project].description : "Your task, choices and progress in one place."}</p></div>${button("■ Stop task", "stop", "danger", !busy() && state.status !== "ready")}</div>
      ${state.returnNotice ? `<div class="return-note"><p><strong>Welcome back.</strong> ${state.status === "uncertain" ? "Your last task needs checking before anything else can happen." : "Here’s the progress saved in this tab. No new task has been started."}</p>${button("Dismiss", "dismiss-return", "text-button")}</div>` : ""}`;
    if (state.view === "results") return header + `<section class="panel"><h2>${state.status === "completed" ? "Your latest result" : "Result so far"}</h2>${resultContent()}</section>`;
    if (state.view === "activity") return header + `<section class="panel"><h2>Task history</h2><p class="subnote">Steps from this demo, in order. This history belongs to this browser tab.</p>${history(true)}</section>`;
    if (state.view === "settings") return header + settings();
    return header + `<div class="health-strip ${needsAttention() ? "attention-health" : ""}"><span class="status-badge">${statuses[state.status]}</span>${needsAttention() ? '<a href="#attention" data-focus="attention-link">1 thing needs your attention ↓</a>' : '<span>Nothing needs your attention</span>'}</div>
      <div class="dashboard-grid"><div>${progress()}<div id="attention" tabindex="-1">${attention()}</div><section class="panel"><div class="section-heading"><h2>${state.status === "completed" ? "Your latest result" : "Recent results"}</h2>${button("View results", "show-results", "text-button")}</div>${resultContent()}</section></div>
      <aside>${resources()}<section class="panel"><h2>Working with ${provider().name}</h2><p>Demo connection · ${permission()}</p><p class="subnote">Only ${state.project} is in scope. No publishing or going live.</p></section><section class="panel"><div class="section-heading"><h2>Recent activity</h2>${button("All activity", "show-activity", "text-button")}</div>${history()}</section></aside></div>`;
  }
  function save() {
    try { sessionStorage.setItem(key, JSON.stringify(state)); } catch { storageAvailable = false; }
  }
  function render(focusPage = false, focusKey = null) {
    clearTimeout(timer);
    const focused = focusKey || document.activeElement?.dataset.focus;
    document.querySelectorAll("details[data-disclosure]").forEach(el => openDetails.set(el.dataset.disclosure, el.open));
    save();
    document.body.classList.toggle("in-workspace", state.step === 7);
    nav.setAttribute("aria-label", state.step === 7 ? "Workspace" : "Setup progress");
    if (state.step === 7) {
      nav.innerHTML = Object.entries(names).map(([id, title]) => `<button class="workspace-nav ${state.view === id ? "current" : ""}" data-view="${id}" data-focus="nav-${id}" ${state.view === id ? 'aria-current="page"' : ""}>${title}${id === "overview" && needsAttention() ? '<span class="nav-count" aria-label="1 item needs attention">1</span>' : ""}</button>`).join("");
      document.getElementById("workspace-label").innerHTML = `<span class="workspace-icon">${state.project[0]}</span><div>${state.project}<small>Example project</small></div>`;
    } else {
      nav.innerHTML = setupNames.map((name, i) => `<div class="step ${i === setupIndex() ? "current" : ""}" ${i === setupIndex() ? 'aria-current="step"' : ""}><span class="step-number">${i < setupIndex() ? "✓" : i || "◇"}</span>${name}</div>`).join("");
      document.getElementById("workspace-label").innerHTML = '<span class="workspace-icon">W</span><div>Your workspace<small>Let’s get started</small></div>';
    }
    document.getElementById("breadcrumb").textContent = state.step === 7 ? `${state.project} / ${names[state.view]}` : "Welcome to DAF";
    content.innerHTML = [welcome, chooseProvider, connect, projects, boundaries, verification, firstTask, dashboard][state.step]() +
      (!storageAvailable ? '<p class="callout warning">This browser cannot save demo progress. You can still try everything here, but reloading the page will start the demo over.</p>' : "");
    document.querySelectorAll("details[data-disclosure]").forEach(el => { el.open = openDetails.get(el.dataset.disclosure) || false; });
    if (focusPage) { content.focus(); window.scrollTo(0, 0); }
    else if (focused) (document.querySelector(`[data-focus="${CSS.escape(focused)}"]`) || content).focus({ preventScroll: true });
    document.getElementById("announcements").textContent = state.step === 7 ? statuses[state.status] : state.step === 5 ? (state.checkStatus === "failed" ? "A setup check needs your attention. Your task has not started." : "Checking your setup automatically.") : "";
    schedule();
  }
  function schedule() {
    clearTimeout(timer);
    if (document.hidden) return;
    if (state.step === 5 && state.checkStatus === "checking") timer = setTimeout(() => { sim.verify(state); render(true); }, 750);
    else if (["running", "validating"].includes(state.status)) timer = setTimeout(() => { sim.tick(state); render(); }, 1800);
  }
  content.addEventListener("click", event => {
    const control = event.target.closest("button[data-action]");
    if (!control || control.disabled) return;
    const action = control.dataset.action;
    let page = false; let focusKey = null;
    if (action === "next") page = sim.next(state);
    if (action === "back") page = sim.back(state);
    if (action === "connect") page = sim.connect(state);
    if (action === "retry-check") page = sim.beginCheck(state);
    if (action === "fix-check") { sim.fixCheck(state); page = true; }
    if (action === "custom") { sim.chooseTask(state, "custom"); focusKey = "customTask"; }
    if (action === "begin") {
      if (!sim.prepare(state)) {
        document.getElementById("task-error").textContent = "Write a short task, or choose one of the suggested tasks above. Up to 500 characters is plenty.";
        document.getElementById("customTask")?.focus(); return;
      }
      sim.start(state); page = true;
    }
    if (action === "stop") { sim.stop(state); state.view = "overview"; page = true; }
    if (action === "allow" || action === "deny") sim.decide(state, Number(control.dataset.approval), action === "allow");
    if (action === "disconnect") { sim.disconnect(state); state.view = "overview"; page = true; }
    if (action === "time-limit") { sim.elapse(state, state.minutes * 60); state.view = "overview"; page = true; }
    if (action === "reconcile") sim.reconcile(state);
    if (action === "fix-recovery") { state.recoveryUnavailable = false; sim.reconcile(state); }
    if (action === "dismiss-return") state.returnNotice = false;
    if (action.startsWith("show-")) { state.view = action.slice(5); page = true; }
    if (action === "reset" && !busy()) { state = sim.initial(); openDetails.clear(); page = true; }
    render(page, focusKey);
  });
  nav.addEventListener("click", event => {
    const target = event.target.closest("button[data-view]");
    if (target && state.step === 7 && names[target.dataset.view]) { state.view = target.dataset.view; render(true); }
  });
  content.addEventListener("change", event => {
    const { name, value } = event.target;
    if (["provider", "project", "mode", "tokens", "minutes", "setupIssue"].includes(name)) {
      sim.configuration(state, name, ["tokens", "minutes"].includes(name) ? Number(value) : value); render();
    }
    if (name === "taskKind") { sim.chooseTask(state, value); render(); }
    if (name === "scenario" && state.status === "ready" && ["normal", "check-failure", "limit", "connection-lost"].includes(value)) { state.scenario = value; save(); }
    if (name === "recoveryUnavailable" && state.status === "uncertain") { state.recoveryUnavailable = event.target.checked; save(); }
  });
  content.addEventListener("input", event => {
    if (event.target.id === "customTask" && state.step === 6) {
      state.customTask = event.target.value;
      sim.chooseTask(state, "custom"); save();
      content.querySelectorAll('[name="taskKind"]').forEach(el => { el.checked = false; el.closest('.choice').classList.remove('selected'); });
    }
  });
  let lastTime = Date.now();
  function updateTime() {
    const now = Date.now(); const delta = Math.floor((now - lastTime) / 1000);
    if (!delta) return;
    lastTime += delta * 1000;
    const before = state.status; sim.elapse(state, delta);
    if (before !== state.status) render(); else if (sim.active.includes(state.status)) save();
  }
  setInterval(() => { if (!document.hidden) updateTime(); }, 1000);
  document.addEventListener("visibilitychange", () => {
    clearTimeout(timer);
    if (!document.hidden) { updateTime(); schedule(); }
  });
  render();
})();

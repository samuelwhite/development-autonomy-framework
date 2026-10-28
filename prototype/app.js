(function () {
  "use strict";
  const sim = window.DAFSimulation;
  const key = "daf-v02-offline-prototype";
  let state = sim.initial();
  let storageAvailable = true;
  try { state = sim.restore(sessionStorage.getItem(key)); } catch { storageAvailable = false; }
  let timer;
  let verificationError = false;
  const content = document.getElementById("content");
  const steps = ["Welcome", "Choose your agent", "Connect", "Choose a project", "Set boundaries", "Verify connection", "Your first task", "Mission Control"];
  const escape = value => String(value).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const button = (label, action, type = "primary", disabled = false) => `<button class="${type}" data-action="${action}" ${disabled ? "disabled" : ""}>${label}</button>`;
  const intro = (title, body) => `<p class="eyebrow">SETUP · ${state.step} OF 6</p><h1>${title}</h1><p class="lead">${body}</p>`;
  const backNext = (disabled = false) => `<div class="actions">${button("← Back", "back", "text-button")} ${button("Continue →", "next", "primary", disabled)}</div>`;
  const provider = () => sim.providers[state.provider];
  const mode = () => state.mode === "review" ? "Review only" : "Supervised edits";
  function choice(field, value, title, body, extra = "") {
    return `<label class="choice ${state[field] === value ? "selected" : ""}"><input type="radio" name="${field}" value="${value}" ${state[field] === value ? "checked" : ""}>${extra}<h2>${title}</h2><p>${body}</p></label>`;
  }
  function welcome() {
    return `<p class="eyebrow">LESS SETUP. MORE MAKING.</p><div class="hero"><div><h1>Your next task.<br><em>Under your control.</em></h1><p class="lead">Bring your AI development agent into a workspace with clear boundaries, visible progress and a stop button that’s always within reach.</p>${button("Let’s get set up →", "next")}<p class="subnote">About 3 minutes · No installation for this demo</p></div><div class="preview-card" aria-label="Illustrative Mission Control"><div class="mini-top"><strong>Mission Control</strong><span class="pill">SIMULATED</span></div><h2>A clearer getting-started guide</h2><p class="subnote">Fieldnotes / Sample project</p><div class="mini-row"><span class="check">✓</span> Boundaries set by you</div><div class="mini-row"><span class="check">✓</span> Every step visible</div><div class="mini-row"><span class="check">○</span> Waiting for your review</div><div class="mini-foot"><span>One task. One agent.</span><span>$0 real spend</span></div></div></div><div class="features"><div><div class="feature-number">01 / CONNECT</div><h3>Your choice of agent</h3><p>Try the Codex or Claude Code setup experience.</p></div><div><div class="feature-number">02 / SET LIMITS</div><h3>Start with less access</h3><p>Review first. Decide when a change is allowed.</p></div><div><div class="feature-number">03 / STAY IN CONTROL</div><h3>A clear next step</h3><p>See what happened, stop work and inspect recovery.</p></div></div>`;
  }
  function chooseProvider() {
    return intro("Who would you like to work with?", "Choose one agent to get started. Both connections are simulated here.") +
      `<div class="cards">${choice("provider", "codex", "OpenAI Codex", "Proposed connection: sign in through the provider’s browser flow. Account eligibility applies.", '<span class="symbol">◎</span><span class="pill">SIMULATED</span>')}${choice("provider", "claude", "Claude Code", "Proposed connection: Claude Agent SDK with an API account. Separately billed from a Claude subscription.", '<span class="symbol">✳</span><span class="pill">SIMULATED</span>')}</div><div class="future"><span>More agents and local models, potentially Ollama</span><span>Planned · unavailable in this prototype</span></div>` + backNext();
  }
  function connect() {
    const codex = state.provider === "codex";
    return intro(`Connect ${provider().name}`, "Try the guided connection. No sign-in page will open and no account will be accessed.") +
      `<section class="panel"><ol class="connection-steps"><li><div>Find the provider<small>Simulated installation detected. A future app will check a supported version and help with installation.</small></div></li><li><div>${codex ? "Sign in with your provider" : "Connect an API account"}<small>${codex ? "The real flow would open the provider’s secure browser sign-in. DAF would receive status, never your password." : "A real integration would use an API key stored in the operating system’s credential store. This demo never asks for a key."}</small></div></li><li><div>Return to DAF<small>Review the connection and spending mode before starting a task.</small></div></li></ol>${state.connected ? '<div class="callout" role="status">✓ Simulated connection ready. No real authentication occurred.</div>' : button(codex ? "Simulate browser sign-in" : "Simulate API connection", "connect")}${!codex ? '<div class="callout warning">Claude subscription login is not offered for this third-party integration without Anthropic approval. API usage has separate billing.</div>' : '<p class="subnote">Future connection options depend on your account and the supported provider version.</p>'}</section>` + backNext(!state.connected);
  }
  function projects() {
    return intro("Where shall we start?", "Pick a sample project. No directories are opened or read; these are fictional workspaces.") + `<div class="cards">${choice("project", "Fieldnotes", "Fieldnotes", "A small notes app. Start by improving its getting-started guide.", '<span class="symbol">▤</span><span class="pill">SAMPLE PROJECT</span>')}${choice("project", "Little Library", "Little Library", "A book collection app. Review its sample README and suggest improvements.", '<span class="symbol">▥</span><span class="pill">SAMPLE PROJECT</span>')}</div><div class="callout">In the real app, “Choose folder” will open your system’s folder picker. DAF will show the exact location and prepare an isolated worktree before any edits.</div>` + backNext();
  }
  function boundaries() {
    return intro("Small scope. Clear limits.", "Start with a review, or try approving a sample edit. These settings affect only the simulation.") +
      `<div class="cards">${choice("mode", "review", "Review only", "Recommended. Read the sample README and suggest a change. No edit approval needed.")}${choice("mode", "edit", "Supervised edits", "Pause before the sample README edit. Approve once or deny; then inspect simulated checks.")}</div><div class="panel"><h2>Your task boundaries</h2><div class="permissions"><div>Project access <span>Selected sample only</span></div><div>File edits <span>${state.mode === "review" ? "Blocked" : "Ask each time"}</span></div><div>Shell & tool network <span>Blocked</span></div><div>Merge & deploy <span>Blocked</span></div><div>Concurrent tasks <span>1</span></div><div>Automatic retries <span>0</span></div></div><div class="form-row"><label class="field">Fixture token ceiling<select name="tokens"><option value="1000" ${state.tokens === 1000 ? "selected" : ""}>1,000 simulated tokens</option><option value="2000" ${state.tokens === 2000 ? "selected" : ""}>2,000 simulated tokens</option></select><small>A sample attempt reserves 800 tokens.</small></label><label class="field">Task time limit<select name="minutes"><option value="5" ${state.minutes === 5 ? "selected" : ""}>5 minutes</option><option value="10" ${state.minutes === 10 ? "selected" : ""}>10 minutes</option></select><small>The simulation stops at this limit, including while waiting for approval.</small></label></div><div class="callout"><strong>Real spending: $0 · Paid requests disabled</strong><br>A real connection must distinguish estimates, provider usage limits and enforceable caps. If a required hard cap cannot be guaranteed, the task must stay blocked.</div></div>` + backNext();
  }
  function verification() {
    return intro("A quick check before you begin.", "This verifies the demo settings only. No provider endpoint or model is contacted.") +
      `<div class="panel">${["Simulated provider connection", "Sample project scope", "Permissions and limits", "Stop and recovery fixture"].map(x => `<div class="verify-row"><span>${x}</span><span class="check">${state.verified ? "✓ Fixture passed" : "Not checked"}</span></div>`).join("")}<div class="compact">${button(state.verified ? "Verify again" : "Verify simulated connection", "verify")}${button("Try a failed check", "verify-fail", "secondary")}</div>${verificationError ? '<p role="alert" class="error">Simulated permission mismatch. Starting is blocked. Use “Verify simulated connection” to retry the fixture check.</p>' : ""}${state.verified ? '<p class="subnote" role="status">All fixture checks passed. This is not proof of a real connection or sandbox.</p>' : ""}</div>` + backNext(!state.verified);
  }
  function firstTask() {
    return intro("Let’s give it a small task.", "Review the scope, then prepare your first supervised simulation.") + `<div class="panel"><label class="field" for="task">What would you like help with?</label><textarea id="task" maxlength="500">${escape(state.task)}</textarea><p class="subnote">Your text stays in this tab. The demo always plays the same README fixture; it does not interpret your request.</p><dl class="details-list"><div><dt>AGENT & PROJECT</dt><dd>${provider().name} · ${state.project} · Simulated</dd></div><div><dt>BOUNDARIES</dt><dd>${mode()} · ${state.tokens.toLocaleString()} fixture tokens · ${state.minutes} minutes · No retries</dd></div><div><dt>EXPECTED RESULT</dt><dd>${state.mode === "review" ? "A suggestion you can review. No files changed." : "A sample README diff, one approval and independent simulated checks."}</dd></div></dl></div><div class="actions">${button("← Back", "back", "text-button")}${button("Prepare my task →", "prepare")}</div><p id="task-error" class="error" role="alert"></p>`;
  }
  const statuses = { ready: "READY WHEN YOU ARE", running: "SIMULATION RUNNING", awaiting_approval: "YOUR APPROVAL NEEDED", validating: "SIMULATED CHECKS RUNNING", completed: "SIMULATION COMPLETE", stopped: "STOPPED", failed: "CHECK FAILED · BLOCKED", limited: "BUDGET LIMIT · BLOCKED", uncertain: "OUTCOME UNKNOWN · BLOCKED" };
  function taskControls() {
    if (state.status === "ready") return button("Start simulation", "start");
    if (state.status === "uncertain") return `<div class="callout warning"><strong>Inspect before restarting.</strong><br>The existing attempt may still be active. Its 800-token reservation is retained. A local stop alone would not prove remote cancellation.</div><div class="compact">${button("Reconcile existing attempt", "reconcile")}</div>`;
    if (state.status === "awaiting_approval") return `<div class="callout"><strong>Allow this one sample edit?</strong><br>README.md in ${state.project} only. Shell, network and other files stay blocked.</div><pre class="diff">- Start the app.
+ Getting started
+ Open the sample project and follow the setup guide.</pre><div class="compact"><button class="primary" data-action="allow" data-approval="${state.approval}">Approve sample edit once</button><button class="secondary" data-action="deny" data-approval="${state.approval}">Deny and stop</button></div>`;
    if (state.status === "completed") return `<div class="callout"><strong>${state.mode === "review" ? "Suggestion ready" : "Sample change ready for review"}</strong><br>${state.mode === "review" ? "Add a Getting started heading and explain the first step in the sample README." : "The fixture’s independent checks passed. Your real project has not changed."}</div>`;
    if (state.status === "stopped") return '<div class="callout">The simulation is stopped. Nothing will resume automatically. Set up another simulation when you are ready.</div>';
    if (state.status === "failed") return '<div class="callout warning">The fixture check found a missing heading. The task is not accepted. No automatic retry is allowed by this plan.</div>';
    if (state.status === "limited") return '<div class="callout warning">The next segment exceeds the remaining fixture budget. The limit stays in place; no automatic increase or retry.</div>';
    return '<p class="subnote">Playing a deterministic fixture. You can stop it at any time.</p>';
  }
  function dashboard() {
    const isActive = ["running", "awaiting_approval", "validating", "uncertain"].includes(state.status);
    return `<div class="dashboard-top"><div><p class="eyebrow">YOUR LOCAL WORKSPACE</p><h1>Mission Control</h1><p class="lead">One task. Clear boundaries. You’re in charge.</p></div>${button("■ Stop task", "stop", "danger", !isActive && state.status !== "ready")}</div><div class="stats"><div class="stat"><small>PROVIDER</small><strong>${state.provider === "codex" ? "Codex" : "Claude"}</strong><p>Simulated connection</p></div><div class="stat"><small>REAL SPEND</small><strong>$0.00</strong><p>Paid requests disabled</p></div><div class="stat"><small>FIXTURE TOKENS</small><strong>${state.used.toLocaleString()} <small>/ ${state.tokens.toLocaleString()}</small></strong><p>${state.reserved} reserved · simulated</p></div><div class="stat"><small>PERMISSIONS</small><strong>${state.mode === "review" ? "Read only" : "Ask first"}</strong><p>1 task · ${state.minutes} min · 0 retries</p></div></div><div class="dashboard-grid"><section class="panel"><p class="status" role="status">${statuses[state.status]}</p><h2 class="task-title">${escape(state.task)}</h2><p class="subnote">${state.project} / README.md · Sample task ${state.attempt ? "· Attempt 1" : ""}</p>${taskControls()}<ol class="timeline" aria-label="Simulation activity">${state.events.map(e => `<li><small>EVENT ${String(e.id).padStart(2, "0")} · SIMULATED</small>${escape(e.text)}</li>`).join("")}</ol></section><aside><section class="panel"><h2>Boundaries at a glance</h2><dl class="details-list"><div><dt>WORKSPACE</dt><dd>${state.project} · Fictional project</dd></div><div><dt>FILE CHANGES</dt><dd>${mode()}</dd></div><div><dt>SHELL / TOOL NETWORK</dt><dd>Blocked / Blocked</dd></div><div><dt>MERGE / DEPLOY</dt><dd>Blocked / Blocked</dd></div><div><dt>STATE & RECOVERY</dt><dd>Saved in this browser tab when available. Reloading active work blocks the fixture for reconciliation. This is not a durable execution journal.</dd></div></dl></section><details class="panel scenario"><summary>Try a failure scenario</summary><p class="subnote">Deterministic fixtures for Product review.</p><label class="field">On the next simulated run<select name="scenario" ${state.status !== "ready" ? "disabled" : ""}><option value="normal" ${state.scenario === "normal" ? "selected" : ""}>Normal task</option><option value="check-failure" ${state.scenario === "check-failure" ? "selected" : ""} ${state.mode === "review" ? "disabled" : ""}>Failed check (supervised edits)</option><option value="limit" ${state.scenario === "limit" ? "selected" : ""}>Budget limit</option><option value="connection-lost" ${state.scenario === "connection-lost" ? "selected" : ""}>Connection lost</option></select></label><div class="compact">${button("Simulate connection loss", "disconnect", "secondary", !["running", "awaiting_approval", "validating"].includes(state.status))}</div></details></aside></div><div class="actions"><span class="subnote">Simulation only · No real provider requests</span>${button("Set up another simulation", "reset", "secondary", isActive)}</div>`;
  }
  function save() {
    try { sessionStorage.setItem(key, JSON.stringify(state)); } catch { storageAvailable = false; }
  }
  function render(focus = false) {
    clearTimeout(timer);
    save();
    document.getElementById("breadcrumb").textContent = `Workspace / ${steps[state.step]}`;
    document.getElementById("steps").innerHTML = steps.map((label, i) => `<div class="step ${i === state.step ? "current" : ""}" ${i === state.step ? 'aria-current="step"' : ""}><span class="step-number">${i < state.step ? "✓" : i + 1}</span>${label}</div>`).join("");
    content.innerHTML = [welcome, chooseProvider, connect, projects, boundaries, verification, firstTask, dashboard][state.step]() + (!storageAvailable ? '<p class="callout warning">Browser storage is unavailable. This demo works in memory; reloading resets it and cannot resume any work.</p>' : "");
    if (focus) { content.focus(); window.scrollTo(0, 0); }
    if (["running", "validating"].includes(state.status)) timer = setTimeout(() => { sim.tick(state); render(); }, 1400);
  }
  content.addEventListener("click", event => {
    const control = event.target.closest("button[data-action]");
    if (!control || control.disabled) return;
    const action = control.dataset.action;
    let focus = false;
    if (action === "next") focus = sim.next(state);
    if (action === "back" && state.step > 0 && state.step < 7) { state.step--; focus = true; }
    if (action === "connect") state.connected = true;
    if (action === "verify" || action === "verify-fail") { verificationError = !sim.verify(state, action === "verify-fail"); }
    if (action === "prepare") {
      if (!sim.prepare(state, document.getElementById("task").value)) { document.getElementById("task-error").textContent = "Enter a short task before continuing (up to 500 characters)."; return; }
      focus = true;
    }
    if (action === "start") sim.start(state);
    if (action === "stop") sim.stop(state);
    if (action === "allow" || action === "deny") sim.decide(state, Number(control.dataset.approval), action === "allow");
    if (action === "disconnect") sim.disconnect(state);
    if (action === "reconcile") sim.reconcile(state);
    if (action === "reset" && !["running", "validating", "awaiting_approval", "uncertain"].includes(state.status)) { state = sim.initial(); verificationError = false; focus = true; }
    render(focus);
  });
  content.addEventListener("change", event => {
    const { name, value } = event.target;
    if (["provider", "project", "mode", "tokens", "minutes"].includes(name)) {
      sim.configuration(state, name, ["tokens", "minutes"].includes(name) ? Number(value) : value);
      verificationError = false; render();
      // Keep keyboard focus on the changed control after replacing the view.
      content.querySelector(`[name="${name}"][value="${value}"]`)?.focus();
      if (["tokens", "minutes"].includes(name)) content.querySelector(`[name="${name}"]`)?.focus();
    }
    if (name === "scenario" && state.status === "ready" && ["normal", "check-failure", "limit", "connection-lost"].includes(value)) { state.scenario = value; save(); }
  });
  content.addEventListener("input", event => {
    if (event.target.id === "task") { state.task = event.target.value; save(); }
  });
  let lastTime = Date.now();
  setInterval(() => {
    const now = Date.now(); const delta = Math.floor((now - lastTime) / 1000);
    if (!delta) return;
    lastTime += delta * 1000;
    const before = state.status;
    sim.elapse(state, delta);
    if (before !== state.status) render();
    else if (["running", "validating", "awaiting_approval"].includes(state.status)) save();
  }, 1000);
  render();
})();

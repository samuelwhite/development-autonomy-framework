/* Deterministic UI fixture. No provider, filesystem, credential or transport APIs. */
(function (root) {
  "use strict";
  const providers = Object.freeze({ codex: { name: "OpenAI Codex" }, claude: { name: "Claude Code" } });
  const projects = Object.freeze({
    Fieldnotes: { description: "An example app for collecting notes and ideas", firstStep: "Create a note, give it a title, then save it to your notebook." },
    "Little Library": { description: "An example app for keeping track of books", firstStep: "Add a book, choose its reading status, then open your collection." }
  });
  const tasks = Object.freeze({
    documentation: { title: "Help improve the getting-started guide", outcome: "A clearer introduction that helps someone use the project for the first time." },
    review: { title: "Review the project and suggest improvements", outcome: "Three practical ideas, with a recommendation on where to start." },
    plan: { title: "Help me plan a small change", outcome: "A short, manageable plan for adding search. Nothing will be changed." }
  });
  const active = ["running", "awaiting_approval", "validating"];
  const scenarios = ["normal", "check-failure", "limit", "connection-lost"];
  const setupIssues = ["none", "connection", "permissions", "limits"];
  function initial() {
    return { version: 2, step: 0, provider: "", connected: false, project: "Fieldnotes",
      mode: "review", tokens: 1000, minutes: 5, verified: false, checkStatus: "idle",
      setupIssue: "none", checkError: null, taskKind: "documentation", customTask: "",
      task: tasks.documentation.title, scenario: "normal", status: "ready", phase: 0,
      used: 0, reserved: 0, attempt: 0, events: [], approval: null, approvalCounter: 0,
      elapsed: 0, view: "overview", returnNotice: false, recoveryUnavailable: false,
      recoveryFailed: false, stopReason: null };
  }
  function log(s, text) {
    s.events.push({ id: (s.events.at(-1)?.id || 0) + 1, text });
    if (s.events.length > 100) s.events.shift();
  }
  function edits(s) { return s.mode === "edit" && ["documentation", "custom"].includes(s.taskKind); }
  function configuration(s, key, value) {
    if (s.step === 7) return false;
    const values = { provider: Object.keys(providers), project: Object.keys(projects),
      mode: ["review", "edit"], tokens: [1000, 2000], minutes: [5, 10], setupIssue: setupIssues };
    if (!values[key]?.includes(value)) return false;
    if (key === "provider" && s.provider !== value) s.connected = false;
    s[key] = value; s.verified = false; s.checkStatus = "idle"; s.checkError = null;
    return true;
  }
  function connect(s) {
    if (s.step !== 2 || !providers[s.provider]) return false;
    s.connected = true; s.step = 3; return true;
  }
  function next(s) {
    if (s.step >= 5 || s.step === 2 || (s.step === 1 && !providers[s.provider])) return false;
    s.step++;
    if (s.step === 5) beginCheck(s);
    return true;
  }
  function back(s) {
    if (s.step < 1 || s.step > 6) return false;
    s.step = s.step >= 5 ? 4 : s.step - 1;
    s.checkStatus = "idle"; s.verified = false; s.checkError = null;
    return true;
  }
  function beginCheck(s) {
    if (s.step !== 5) return false;
    s.checkStatus = "checking"; s.verified = false; s.checkError = null; return true;
  }
  function verify(s) {
    if (s.step !== 5 || s.checkStatus !== "checking") return false;
    let issue = s.setupIssue;
    if (!s.connected || !providers[s.provider]) issue = "connection";
    else if (!projects[s.project] || !["review", "edit"].includes(s.mode)) issue = "permissions";
    else if (![1000, 2000].includes(s.tokens) || ![5, 10].includes(s.minutes)) issue = "limits";
    s.checkError = issue === "none" ? null : issue;
    s.verified = !s.checkError;
    s.checkStatus = s.verified ? "passed" : "failed";
    if (s.verified) s.step = 6;
    return s.verified;
  }
  function fixCheck(s) {
    if (s.step !== 5 || s.checkStatus !== "failed") return false;
    if (s.checkError === "connection") {
      if (!providers[s.provider]) { s.step = 1; return false; }
      s.connected = true;
    } else if (s.checkError === "permissions") {
      s.mode = "review"; // The visible action explicitly switches to suggestions only.
      if (!projects[s.project]) s.project = "Fieldnotes";
    } else if (s.checkError === "limits") { s.tokens = 1000; s.minutes = 5; }
    else return false;
    s.setupIssue = "none";
    return beginCheck(s); // A fix rechecks; it cannot mark itself verified.
  }
  function chooseTask(s, kind) {
    if (s.step !== 6 || ![...Object.keys(tasks), "custom"].includes(kind)) return false;
    s.taskKind = kind;
    s.task = kind === "custom" ? s.customTask.trim() : tasks[kind].title;
    return true;
  }
  function prepare(s) {
    if (!s.verified || !s.connected || !providers[s.provider] || s.step !== 6) return false;
    const text = s.taskKind === "custom" ? s.customTask.trim() : tasks[s.taskKind]?.title;
    if (!text || text.length > 500) return false;
    s.task = text; s.step = 7; s.view = "overview";
    log(s, "Your task and permissions are ready."); return true;
  }
  function start(s) {
    if (s.step !== 7 || !s.verified || !s.connected || !providers[s.provider] || s.status !== "ready") return false;
    s.attempt++; s.reserved = 800; s.status = "running";
    log(s, "Started your example task. Enough of the demo allowance has been set aside to finish it."); return true;
  }
  function tick(s) {
    if (!["running", "validating"].includes(s.status)) return;
    if (s.status === "validating") {
      s.used = 800; s.reserved = 0;
      s.status = s.scenario === "check-failure" ? "failed" : "completed";
      if (s.status === "completed") s.phase = 3;
      log(s, s.status === "failed" ? "The example result did not pass its separate quality check. It has not been accepted." :
        edits(s) ? "The approved example change passed its separate checks. Your result is ready." : "Your suggestions are ready. Nothing was changed.");
      return;
    }
    s.phase++;
    if (s.phase === 1) { log(s, `Looked through ${s.project}’s example introduction.`); return; }
    if (s.scenario === "connection-lost") { s.phase = 1; disconnect(s); return; }
    if (s.scenario === "limit") {
      s.phase = 1; s.status = "limited"; s.used = 800; s.reserved = 0;
      log(s, "Stopped before the next step: it would exceed your demo allowance. The limit has not been increased."); return;
    }
    log(s, s.taskKind === "plan" ? "Prepared a small plan for adding search." : s.taskKind === "review" ? "Prepared three practical suggestions." : "Prepared a clearer getting-started section.");
    if (edits(s)) {
      s.status = "awaiting_approval"; s.approval = ++s.approvalCounter;
      log(s, "Waiting for your permission to apply this one example change.");
    } else s.status = "validating";
  }
  function decide(s, id, allow) {
    if (s.status !== "awaiting_approval" || id !== s.approval) return false;
    s.approval = null;
    if (allow) { s.status = "validating"; log(s, "You approved the example change. Checking it before calling the task complete."); }
    else {
      s.status = "stopped"; s.reserved = 0; s.used = 400; s.stopReason = "denied";
      log(s, "You declined the change. Work stopped without applying it.");
    }
    return true;
  }
  function stop(s) {
    if (s.status === "uncertain") { log(s, "New work remains blocked. Check the earlier work to find out whether it stopped."); return; }
    if (![...active, "ready"].includes(s.status)) return;
    s.used = s.phase ? 400 : 0;
    s.status = "stopped"; s.approval = null; s.reserved = 0; s.stopReason = "requested";
    log(s, "You stopped the demo. Any pending permission request was cancelled. Nothing will restart by itself.");
  }
  function disconnect(s) {
    if (!active.includes(s.status)) return;
    s.status = "uncertain"; s.approval = null;
    log(s, "Lost track of the example task. Its allowance is still set aside, and new work is blocked until it can be checked.");
  }
  function reconcile(s) {
    if (s.status !== "uncertain") return false;
    if (s.recoveryUnavailable) {
      s.recoveryFailed = true; log(s, "The demo could not confirm the earlier result. No replacement task was started."); return false;
    }
    s.status = "stopped"; s.used = 400; s.reserved = 0; s.recoveryFailed = false; s.stopReason = "recovered";
    log(s, "Checked the original task and confirmed it stopped. No duplicate task was created."); return true;
  }
  function elapse(s, seconds) {
    if (!active.includes(s.status) || !Number.isInteger(seconds) || seconds < 0) return;
    s.elapsed += seconds;
    if (s.elapsed >= s.minutes * 60) { stop(s); s.stopReason = "time"; log(s, "Reached your time limit and stopped, without extending it."); }
  }
  function milestones(s) {
    const labels = ["Understand the example project", s.taskKind === "plan" ? "Prepare a small plan" : "Prepare the improvements", "Check the result"];
    return labels.map((label, index) => ({ label, state: s.phase > index ? "done" :
      (active.includes(s.status) && s.phase === index ? "current" : "next") }));
  }
  // Browser storage is presentation only; active work never resumes on reload.
  function restore(raw) {
    const fallback = initial();
    try {
      const s = JSON.parse(raw);
      if (!s || s.version !== 2 || !["", ...Object.keys(providers)].includes(s.provider) ||
          !Object.keys(projects).includes(s.project) || !["review", "edit"].includes(s.mode) ||
          ![1000, 2000].includes(s.tokens) || ![5, 10].includes(s.minutes) ||
          !Number.isInteger(s.step) || s.step < 0 || s.step > 7 ||
          ![s.connected, s.verified, s.returnNotice, s.recoveryUnavailable, s.recoveryFailed].every(v => typeof v === "boolean") ||
          !["idle", "checking", "passed", "failed"].includes(s.checkStatus) ||
          !setupIssues.includes(s.setupIssue) || ![null, "connection", "permissions", "limits"].includes(s.checkError) ||
          (s.checkStatus === "failed" && s.checkError === null) ||
          (s.verified && (s.checkStatus !== "passed" || s.checkError !== null)) ||
          ![...Object.keys(tasks), "custom"].includes(s.taskKind) ||
          ![s.task, s.customTask].every(t => typeof t === "string" && t.length <= 500) ||
          !scenarios.includes(s.scenario) || !["overview", "results", "activity", "settings"].includes(s.view) ||
          ![null, "denied", "requested", "recovered", "time"].includes(s.stopReason) ||
          !["ready", ...active, "stopped", "completed", "failed", "limited", "uncertain"].includes(s.status) ||
          ![s.used, s.reserved, s.attempt, s.phase, s.approvalCounter, s.elapsed].every(n => Number.isInteger(n) && n >= 0 && n <= 10000) ||
          s.phase > 3 || s.attempt > 1 || (s.status === "completed" && s.phase !== 3) ||
          !Array.isArray(s.events) || s.events.length > 100 ||
          !s.events.every(e => Number.isInteger(e.id) && typeof e.text === "string" && e.text.length < 500) ||
          (s.step > 1 && !providers[s.provider]) || (s.step > 2 && !s.connected) ||
          (s.step > 5 && (!s.verified || s.checkStatus !== "passed" || s.checkError !== null || s.setupIssue !== "none")) ||
          (s.step < 7 && s.status !== "ready")) return fallback;
      const result = Object.fromEntries(Object.keys(fallback).map(k => [k, s[k]]));
      result.approval = null;
      if (active.includes(result.status)) disconnect(result);
      if (result.step === 7) result.returnNotice = true;
      return result;
    } catch { return fallback; }
  }
  const api = { providers, projects, tasks, active, initial, configuration, connect, next, back,
    beginCheck, verify, fixCheck, chooseTask, prepare, start, tick, decide, stop, disconnect,
    reconcile, elapse, milestones, edits, restore };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.DAFSimulation = api;
})(globalThis);

/* Deterministic UI fixture. No provider, filesystem, credential or transport APIs. */
(function (root) {
  "use strict";
  const providers = Object.freeze({
    codex: { name: "OpenAI Codex", route: "Provider-managed browser sign-in" },
    claude: { name: "Claude Code", route: "API account connection via Agent SDK" }
  });
  const active = ["running", "awaiting_approval", "validating"];
  function initial() {
    return { version: 1, step: 0, provider: "codex", connected: false, project: "Fieldnotes",
      mode: "review", tokens: 1000, minutes: 5, verified: false,
      task: "Review the sample README and suggest a clearer getting-started section.",
      scenario: "normal", status: "ready", phase: 0, used: 0, reserved: 0,
      attempt: 0, events: [], approval: null, approvalCounter: 0, elapsed: 0 };
  }
  function log(s, text) { s.events.push({ id: s.events.length + 1, text }); }
  function configuration(s, key, value) {
    if (s.step === 7) return false;
    const values = { provider: Object.keys(providers), project: ["Fieldnotes", "Little Library"],
      mode: ["review", "edit"], tokens: [1000, 2000], minutes: [5, 10] };
    if (!values[key]?.includes(value)) return false;
    if (key === "provider" && s.provider !== value) s.connected = false;
    s[key] = value; s.verified = false;
    return true;
  }
  function next(s) {
    if (s.step >= 6 || (s.step === 2 && !s.connected) || (s.step === 5 && !s.verified)) return false;
    s.step++; return true;
  }
  function verify(s, failure = false) {
    s.verified = s.connected && !!providers[s.provider] && !failure;
    return s.verified;
  }
  function prepare(s, task) {
    if (!s.verified || !s.connected || s.step !== 6 || !task.trim() || task.length > 500) return false;
    s.task = task.trim(); s.step = 7;
    log(s, "Task prepared. Waiting for you to start the simulation."); return true;
  }
  function start(s) {
    if (s.step !== 7 || !s.verified || !s.connected || s.status !== "ready") return false;
    s.attempt++; s.reserved = 800; s.status = "running";
    log(s, "Simulated attempt 1 admitted. Reserved 800 fixture tokens; one task only."); return true;
  }
  function tick(s) {
    if (!["running", "validating"].includes(s.status)) return;
    if (s.status === "validating") {
      s.used = 800; s.reserved = 0;
      s.status = s.scenario === "check-failure" ? "failed" : "completed";
      log(s, s.status === "failed" ? "Independent fixture check failed: the getting-started heading is missing. No automatic retry." : "Independent fixture checks passed. Sample diff is ready for review; nothing was merged.");
      return;
    }
    s.phase++;
    if (s.phase === 1) { log(s, "Read the sample README inside the selected fixture project."); return; }
    if (s.scenario === "connection-lost") { disconnect(s); return; }
    if (s.scenario === "limit") {
      s.status = "limited"; s.used = 800; s.reserved = 0;
      log(s, "Next segment needs 1,500 fixture tokens. Remaining budget is insufficient. Admission refused."); return;
    }
    if (s.mode === "edit") {
      s.status = "awaiting_approval"; s.approval = ++s.approvalCounter;
      log(s, "Waiting for your one-time approval of the sample README edit.");
    } else {
      s.used = 800; s.reserved = 0; s.status = "completed";
      log(s, "Read-only suggestion prepared. No write permission was requested; no acceptance claim for code changes.");
    }
  }
  function decide(s, id, allow) {
    if (s.status !== "awaiting_approval" || id !== s.approval) return false;
    s.approval = null;
    if (allow) { s.status = "validating"; log(s, "Sample edit approved once. Running independent fixture checks."); }
    else { s.status = "stopped"; s.reserved = 0; s.used = 400; log(s, "Edit denied. Simulated attempt stopped; no change applied."); }
    return true;
  }
  function stop(s) {
    if (s.status === "uncertain") { log(s, "New admissions remain blocked. Existing attempt still needs reconciliation."); return; }
    if (![...active, "ready"].includes(s.status)) return;
    s.status = "stopped"; s.approval = null; s.reserved = 0;
    log(s, "Simulation stopped. Pending approval invalidated; no further steps will run.");
  }
  function disconnect(s) {
    if (!active.includes(s.status)) return;
    s.status = "uncertain"; s.approval = null;
    log(s, "Simulated connection lost. Outcome unknown; reservation retained. New work is blocked.");
  }
  function reconcile(s) {
    if (s.status !== "uncertain") return false;
    s.status = "stopped"; s.used = 400; s.reserved = 0;
    log(s, "Fixture lookup confirms the same attempt stopped. No duplicate attempt was created."); return true;
  }
  function elapse(s, seconds) {
    if (!active.includes(s.status)) return;
    s.elapsed += seconds;
    if (s.elapsed >= s.minutes * 60) { stop(s); log(s, "Selected time limit reached. Simulation stopped."); }
  }
  // Restore only validated presentation state. Browser storage is never execution authority.
  function restore(raw) {
    const fallback = initial();
    try {
      const s = JSON.parse(raw);
      if (!s || s.version !== 1 || !providers[s.provider] ||
          !["Fieldnotes", "Little Library"].includes(s.project) || !["review", "edit"].includes(s.mode) ||
          ![1000, 2000].includes(s.tokens) || ![5, 10].includes(s.minutes) ||
          !Number.isInteger(s.step) || s.step < 0 || s.step > 7 ||
          typeof s.connected !== "boolean" || typeof s.verified !== "boolean" ||
          typeof s.task !== "string" || s.task.length > 500 ||
          !["normal", "check-failure", "limit", "connection-lost"].includes(s.scenario) ||
          !["ready", ...active, "stopped", "completed", "failed", "limited", "uncertain"].includes(s.status) ||
          ![s.used, s.reserved, s.attempt, s.phase, s.approvalCounter, s.elapsed].every(n => Number.isInteger(n) && n >= 0 && n <= 10000) ||
          !Array.isArray(s.events) || s.events.length > 100 ||
          !s.events.every(e => Number.isInteger(e.id) && typeof e.text === "string" && e.text.length < 500) ||
          (s.step > 2 && !s.connected) || (s.step > 5 && !s.verified)) return fallback;
      const result = Object.fromEntries(Object.keys(fallback).map(k => [k, s[k]]));
      result.approval = null;
      if (active.includes(result.status)) disconnect(result);
      return result;
    } catch { return fallback; }
  }
  const api = { providers, initial, configuration, next, verify, prepare, start, tick, decide, stop, disconnect, reconcile, elapse, restore };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.DAFSimulation = api;
})(globalThis);

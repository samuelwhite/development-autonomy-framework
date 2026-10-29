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
  const active = ["running", "awaiting_approval", "validating", "milestone_review", "boundary_pause"];
  const exceptions = ["scope", "permissions", "limit", "unexpected", "publication", "merge", "deployment"];
  const scenarios = ["normal", "check-failure", "limit", "connection-lost", ...exceptions.filter(x => x !== "limit")];
  const setupIssues = ["none", "connection", "permissions", "limits"];
  function initial() {
    return { version: 3, step: 0, provider: "", connected: false, project: "Fieldnotes",
      mode: "review", tokens: 1000, minutes: 5, verified: false, checkStatus: "idle",
      setupIssue: "none", checkError: null, taskKind: "documentation", customTask: "",
      task: tasks.documentation.title, scenario: "normal", status: "ready", phase: 0,
      used: 0, reserved: 0, attempt: 0, events: [], approval: null, approvalCounter: 0,
      elapsed: 0, view: "overview", returnNotice: false, recoveryUnavailable: false,
      recoveryFailed: false, stopReason: null, planReview: false, planDraft: null,
      consents: { plan: false, scope: false, limits: false }, approvedPlan: null,
      milestoneResults: [], exception: null };
  }
  function log(s, text) {
    s.events.push({ id: (s.events.at(-1)?.id || 0) + 1, text });
    if (s.events.length > 100) s.events.shift();
  }
  function edits(s) { return ["edit", "independent"].includes(s.mode) && ["documentation", "custom"].includes(s.taskKind); }
  function clearPlan(s) {
    s.planReview = false; s.planDraft = null; s.approvedPlan = null;
    s.consents = { plan: false, scope: false, limits: false };
  }
  // Fixed, synthetic plans only. This is presentation state, never live authority.
  function planFor(s) {
    const item = s.project === "Fieldnotes" ? "note" : "book";
    const stages = s.taskKind === "review" ? [
      { title: "Review the first-use experience", work: "Recorded three observations about the example introduction.", choices: "Grouped the observations by the reader’s first steps.", evidence: ["Three observations present", "No example content changed"] },
      { title: "Prepare practical suggestions", work: "Prepared three improvements with a recommended starting point.", choices: "Ordered the suggestions by effort and usefulness.", evidence: ["Each suggestion has a reason", "No changes or extra tasks scheduled"] },
      { title: "Check the recommendations", work: "Checked the recommendations against the example and prepared the final review.", choices: "Used a short checklist to make the review easy to follow.", evidence: ["Recommendations stay within the review", "No files changed, published or merged"] }
    ] : s.taskKind === "plan" ? [
      { title: "Define a small search improvement", work: `Outlined a search idea for ${item} titles.`, choices: "Kept the example focused on titles rather than wider search.", evidence: ["One small change described", "No implementation started"] },
      { title: "Break the idea into steps", work: "Prepared three steps: choose the scope, sketch the search, try example entries.", choices: "Ordered the steps so the idea can be tried before building it.", evidence: ["Steps have clear outcomes", "No work scheduled beyond this planning task"] },
      { title: "Check the proposed plan", work: "Checked the plan for missing decisions and prepared it for your review.", choices: "Listed open questions instead of making new product decisions.", evidence: ["Plan stays within the search idea", "No files changed, published or deployed"] }
    ] : [
      { title: "Improve the introduction", work: `Added a getting-started heading and this first step: ${projects[s.project].firstStep}`, choices: "Chose a short heading and arranged the instructions in reading order.", evidence: ["Getting-started heading present", "First step explains what to create and save", "Only the example guide changed"] },
      { title: "Add a worked example", work: `Added a sample ${item} and a short tip explaining how to find it again.`, choices: `Chose a fictional ${item} and placed the tip after the first step.`, evidence: ["Worked example and return tip present", "No application code or other files changed"] },
      { title: "Check the whole guide", work: "Checked the two sections together and prepared the finished example guide.", choices: "Used the agreed checklist; no extra feature or task was added.", evidence: ["Both guide sections pass the fixture checklist", "Scope unchanged; no publication, merge or deployment"] }
    ];
    return { version: "example-plan-1", provider: s.provider, project: s.project, mode: s.mode,
      task: s.taskKind === "custom" ? s.customTask.trim() : tasks[s.taskKind]?.title,
      taskKind: s.taskKind, scenario: s.scenario,
      scope: edits(s) ? `Only the fictional getting-started guide for ${s.project}. Two small documentation improvements and a final check.` : `Only a ${s.taskKind === "plan" ? "written search plan" : "written review"} for ${s.project}. No changes to the example project.`,
      routineChoices: edits(s) ? "Wording, headings, example content and layout within this guide." : "Wording, ordering and presentation within this written result.",
      limits: { minutes: s.minutes, tokens: s.tokens, reserved: 800, tasks: 1, retries: 0, realCost: 0 },
      blocked: ["Other files and application code", "Shell commands and tool internet access", "New features or wider scope", "Publication", "Merging", "Deployment"],
      reviews: "Pause after every verified milestone, including the final result. Pause immediately for exceptions.",
      milestones: stages.map((stage, index) => ({ ...stage, intent: (s.taskKind === "review" ? [
        "Identify three obstacles in the example’s first-use experience.",
        "Recommend three improvements and choose a starting point.",
        "Check that the recommendations stay within this review."
      ] : s.taskKind === "plan" ? [
        `Describe one small search improvement for ${item} titles.`,
        "Outline steps to scope, sketch and try the idea, without implementing it.",
        "Check the plan and list any product decisions that still need you."
      ] : [
        `Add a clear heading and explain how to create a first ${item}.`,
        `Add a fictional ${item} and a tip about finding it again.`,
        "Check both sections against the agreed checklist and prepare the result."
      ])[index] })) };
  }
  function planKey(s) { return JSON.stringify(planFor(s)); }
  function approved(s) {
    return s.mode === "independent" && s.approvedPlan !== null && s.approvedPlan === planKey(s) &&
      ["plan", "scope", "limits"].every(key => s.consents?.[key] === true);
  }
  function reviewPlan(s) {
    if (s.step !== 6 || s.mode !== "independent" || !s.verified || !s.connected) return false;
    const plan = planFor(s);
    if (!plan.task || plan.task.length > 500) return false;
    clearPlan(s); s.planDraft = planKey(s); s.planReview = true; return true;
  }
  function consent(s, key, value) {
    if (s.step !== 6 || !s.planReview || s.planDraft !== planKey(s) ||
        !["plan", "scope", "limits"].includes(key) || typeof value !== "boolean") return false;
    s.consents[key] = value; return true;
  }
  function approvePlan(s) {
    if (s.step !== 6 || !s.planReview || s.planDraft !== planKey(s) ||
        !["plan", "scope", "limits"].every(k => s.consents[k] === true)) return false;
    s.approvedPlan = s.planDraft;
    if (!prepare(s)) { s.approvedPlan = null; return false; }
    log(s, "You approved this example plan, its exact scope, milestone reviews and limits.");
    return start(s);
  }
  function selectScenario(s, scenario) {
    if (s.step !== 6 || s.status !== "ready" || !scenarios.includes(scenario) ||
        (s.mode !== "independent" && !["normal", "check-failure", "limit", "connection-lost"].includes(scenario))) return false;
    s.scenario = scenario; clearPlan(s); return true;
  }
  function raiseException(s, kind) {
    if (s.mode !== "independent" || !active.includes(s.status) || !exceptions.includes(kind)) return false;
    s.status = "boundary_pause"; s.exception = kind; s.approval = null;
    log(s, `Paused immediately for a ${kind} boundary. No extra work was admitted; the approved scope and limits remain unchanged.`);
    return true;
  }
  function planGuard(s) {
    if (!approved(s)) { raiseException(s, "scope"); return false; }
    if (s.elapsed >= s.minutes * 60) { stop(s); s.stopReason = "time"; return false; }
    return true;
  }
  function tickPlan(s) {
    if (!planGuard(s)) return;
    if (s.status === "running") {
      if (s.scenario === "connection-lost") { disconnect(s); return; }
      // Inject exceptions only after the first checked milestone. Validation grants no wider scope.
      if (s.phase === 1 && exceptions.includes(s.scenario)) { raiseException(s, s.scenario); return; }
      const cost = [250, 550, 800][s.phase];
      if (cost === undefined || cost > s.tokens) { raiseException(s, "limit"); return; }
      if (s.milestoneResults.length !== s.phase || s.milestoneResults.some(m => !m.reviewed)) return;
      s.milestoneResults.push({ index: s.phase, check: "pending", reviewed: false });
      s.used = cost; s.reserved = 800 - cost; s.status = "validating";
      log(s, `Milestone ${s.phase + 1}: ${planFor(s).milestones[s.phase].work} Routine choices stayed within your approved plan.`);
      return;
    }
    const result = s.milestoneResults.at(-1);
    if (!result || result.check !== "pending") return;
    if (s.scenario === "check-failure") {
      result.check = "failed"; s.status = "failed"; s.reserved = 0;
      log(s, "The milestone failed its synthetic scope/evidence check. No later milestone or retry was started."); return;
    }
    result.check = "passed"; s.phase++;
    s.status = "milestone_review"; s.approval = ++s.approvalCounter;
    log(s, `Milestone ${s.phase} passed its fixture checks. Paused for your review; this is not permission for the next milestone or wider scope.`);
  }
  function reviewMilestone(s, id, continuePlan) {
    if (s.mode !== "independent" || s.status !== "milestone_review" || s.approval !== id) return false;
    if (!planGuard(s)) return false;
    const result = s.milestoneResults.at(-1);
    if (!result || result.check !== "passed" || result.reviewed) return false;
    s.approval = null;
    if (!continuePlan) { stop(s); s.stopReason = "milestone_declined"; return true; }
    result.reviewed = true;
    log(s, `You reviewed milestone ${s.phase}. The original scope and limits are unchanged.`);
    if (s.phase === 3) {
      s.status = "completed"; s.reserved = 0;
      log(s, "The approved example plan is complete. Nothing was published, merged, deployed or scheduled next.");
    } else s.status = "running";
    return true;
  }
  function configuration(s, key, value) {
    if (s.step === 7) return false;
    const values = { provider: Object.keys(providers), project: Object.keys(projects),
      mode: ["review", "edit", "independent"], tokens: [1000, 2000], minutes: [5, 10], setupIssue: setupIssues };
    if (!values[key]?.includes(value)) return false;
    if (key === "provider" && s.provider !== value) s.connected = false;
    s[key] = value; s.verified = false; s.checkStatus = "idle"; s.checkError = null;
    clearPlan(s);
    if (key === "mode") s.scenario = "normal";
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
    if (s.step === 6 && s.planReview) { clearPlan(s); return true; }
    clearPlan(s);
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
    else if (!projects[s.project] || !["review", "edit", "independent"].includes(s.mode)) issue = "permissions";
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
    clearPlan(s); s.taskKind = kind;
    s.task = kind === "custom" ? s.customTask.trim() : tasks[kind].title;
    return true;
  }
  function prepare(s) {
    if (!s.verified || !s.connected || !providers[s.provider] || s.step !== 6) return false;
    if (s.mode === "independent" && !approved(s)) return false;
    const text = s.taskKind === "custom" ? s.customTask.trim() : tasks[s.taskKind]?.title;
    if (!text || text.length > 500) return false;
    s.task = text; s.step = 7; s.view = "overview"; s.planReview = false;
    log(s, "Your task and permissions are ready."); return true;
  }
  function start(s) {
    if (s.step !== 7 || !s.verified || !s.connected || !providers[s.provider] || s.status !== "ready") return false;
    if (s.attempt !== 0 || (s.mode === "independent" && !approved(s))) return false;
    s.attempt++; s.reserved = 800; s.status = "running";
    log(s, "Started your example task. Enough of the demo allowance has been set aside to finish it."); return true;
  }
  function tick(s) {
    if (!["running", "validating"].includes(s.status)) return;
    if (s.mode === "independent") { tickPlan(s); return; }
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
    if (s.mode !== "independent") s.used = s.phase ? 400 : 0;
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
    s.status = "stopped"; if (s.mode !== "independent") s.used = 400;
    s.reserved = 0; s.recoveryFailed = false; s.stopReason = "recovered";
    log(s, "Checked the original task and confirmed it stopped. No duplicate task was created."); return true;
  }
  function elapse(s, seconds) {
    if (!active.includes(s.status) || !Number.isInteger(seconds) || seconds < 0) return;
    s.elapsed += seconds;
    if (s.elapsed >= s.minutes * 60) { stop(s); s.stopReason = "time"; log(s, "Reached your time limit and stopped, without extending it."); }
  }
  function milestones(s) {
    if (s.mode === "independent") return planFor(s).milestones.map((m, index) => {
      const result = s.milestoneResults[index];
      return { label: m.title, reviewed: result?.reviewed || false,
        state: result?.check === "passed" ? "done" :
          (["running", "validating"].includes(s.status) && s.phase === index ? "current" : "next") };
    });
    const labels = ["Understand the example project", s.taskKind === "plan" ? "Prepare a small plan" : "Prepare the improvements", "Check the result"];
    return labels.map((label, index) => ({ label, state: s.phase > index ? "done" :
      (active.includes(s.status) && s.phase === index ? "current" : "next") }));
  }
  // Browser storage is presentation only; active work never resumes on reload.
  function restore(raw) {
    const fallback = initial();
    try {
      let s = JSON.parse(raw);
      // Preserve older suggestion/edit demonstrations, including interrupted allowances.
      if (s?.version === 2 && ["review", "edit"].includes(s.mode)) s = { ...initial(), ...s, version: 3 };
      if (!s || s.version !== 3 || !["", ...Object.keys(providers)].includes(s.provider) ||
          !Object.keys(projects).includes(s.project) || !["review", "edit", "independent"].includes(s.mode) ||
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
          ![null, "denied", "requested", "recovered", "time", "milestone_declined"].includes(s.stopReason) ||
          !["ready", ...active, "stopped", "completed", "failed", "limited", "uncertain"].includes(s.status) ||
          ![s.used, s.reserved, s.attempt, s.phase, s.approvalCounter, s.elapsed].every(n => Number.isInteger(n) && n >= 0 && n <= 10000) ||
          s.phase > 3 || s.attempt > 1 || (s.status === "completed" && s.phase !== 3) ||
          !Array.isArray(s.events) || s.events.length > 100 ||
          !s.events.every(e => Number.isInteger(e.id) && typeof e.text === "string" && e.text.length < 500) ||
          (s.step > 1 && !providers[s.provider]) || (s.step > 2 && !s.connected) ||
          (s.step > 5 && (!s.verified || s.checkStatus !== "passed" || s.checkError !== null || s.setupIssue !== "none")) ||
          (s.step < 7 && s.status !== "ready")) return fallback;
      if (typeof s.planReview !== "boolean" || !s.consents ||
          !["plan", "scope", "limits"].every(k => typeof s.consents[k] === "boolean") ||
          ![s.planDraft, s.approvedPlan].every(p => p === null || (typeof p === "string" && p.length <= 8000)) ||
          ![null, ...exceptions].includes(s.exception) || !Array.isArray(s.milestoneResults) || s.milestoneResults.length > 3 ||
          !s.milestoneResults.every((m, i) => m.index === i && ["pending", "passed", "failed"].includes(m.check) &&
            typeof m.reviewed === "boolean" && (!m.reviewed || m.check === "passed")) ||
          (s.planReview && (s.step !== 6 || s.mode !== "independent" || s.planDraft !== planKey(s))) ||
          (s.mode === "independent" && s.step === 7 && !approved(s)) ||
          (s.mode !== "independent" && (s.approvedPlan !== null || s.milestoneResults.length || ["milestone_review", "boundary_pause"].includes(s.status))) ||
          (s.mode === "independent" && s.phase !== s.milestoneResults.filter(m => m.check === "passed").length) ||
          (s.status === "milestone_review" && (s.milestoneResults.at(-1)?.check !== "passed" || s.milestoneResults.at(-1)?.reviewed)) ||
          (s.status === "boundary_pause" && s.exception === null) ||
          (s.mode === "independent" && s.status === "completed" && !s.milestoneResults.every(m => m.reviewed))) return fallback;
      const result = Object.fromEntries(Object.keys(fallback).map(k => [k, s[k]]));
      result.approval = null;
      if (active.includes(result.status)) disconnect(result);
      if (result.step === 7) result.returnNotice = true;
      return result;
    } catch { return fallback; }
  }
  const api = { providers, projects, tasks, active, initial, configuration, connect, next, back,
    beginCheck, verify, fixCheck, chooseTask, prepare, start, tick, decide, stop, disconnect,
    reconcile, elapse, milestones, edits, restore, planFor, reviewPlan, consent, approvePlan,
    selectScenario, raiseException, reviewMilestone, exceptions };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.DAFSimulation = api;
})(globalThis);

# Offline walkthrough

Run `python -m daf demo --output ../demo-output` from `src/`, then open the
generated `index.html`. The command exits without leaving a server or worker.

1. **Progression:** F1 succeeds. F2 fails independent fixture validation once;
   DAF records the failure, supplies correction context and retains the successful
   second attempt. F3 depends on F2's acceptance. Four attempts remain visible.
2. **Restart:** the demonstration closes and reopens SQLite connections after
   dispatch, then reopens again after completion. It checks that the result and
   number of simulated provider jobs did not change.
3. **Scope blocker:** a separate scenario asks for changed operating permissions.
   It remains `needs_decision`; a later success in another scenario cannot clear it.
4. **Stop:** another journal commits stop before its first admission. The paused
   scenario has zero jobs. No resume or approval action is exposed in the UI.
5. **Bounded continuation:** two simulated requests each have an immutable binding,
   reservation and deterministic checkpoint. Repeated dispatch reconciles existing
   intent; a third segment is refused at the budget boundary.

The dashboard's token totals are fixture usage, not actual provider billing. A
failed progression attempt still contributes its 100 fixture tokens: the completed
progression totals 400, not 300. The bounded experiment has its own byte-token
accounting and must not be added to the progression's unrelated budget.

`demonstration.json` is the complete safe display projection. The generated SQLite
databases contain synthetic evidence for inspection. No GitHub or external CI
records exist in this demo; the viewer says so. Merging and deployment were not
performed.

For a screenshot or short recording: show the three scenario cards, scroll to
the failed attempt retained alongside its correction, then show the third-segment
budget refusal. Keep the **OFFLINE / SYNTHETIC** label visible. Do not substitute
private product journals or imply that the fixture spend limit is provider-certified.

An existing output directory is always refused. Delete only your own disposable
demo output manually if desired, or select a fresh name. Never point experiments
at another execution journal.

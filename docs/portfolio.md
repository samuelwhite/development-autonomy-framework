# Product review: repository presentation and introduction

**Draft materials only. No metadata change or external announcement has been made.**

## Recommended repository description

> Offline Developer Preview for inspectable AI development orchestration: explicit plans, durable evidence, restart recovery and bounded execution experiments.

## Recommended GitHub topics

`ai-development`, `workflow-orchestration`, `developer-tools`, `python`, `sqlite`,
`state-machine`, `durable-execution`, `offline`, `developer-preview`

These describe the shipped preview and its evaluation scope. Apply them only after
Product has reviewed the proposed description and topics.

## LinkedIn introduction — proposed copy, not posted

I'm sharing DAF — the Development Autonomy Framework — as an offline Developer Preview.

AI development needs more than generated code. I want to inspect the plan, see failed
attempts alongside their corrections, recover without duplicating work, and understand
when work must stop.

DAF explores those ideas through small Python components and synthetic demonstrations.
Its Mission Control snapshot shows milestone progression, retained evidence, a scope
blocker, an emergency stop and bounded continuation experiments.

The source is public under Apache-2.0. The hosted validation matrix passed on Windows
and Linux with Python 3.12 and 3.13, with 145 tests in each job.

This is an offline preview: no model calls, live execution, deployment or API keys.
Its fixture budgets are experiments, not guarantees about real provider spending.

If you're working on AI development tooling, I'd welcome feedback on the control
contracts, recovery behavior and evidence model.

[Explore DAF on GitHub](https://github.com/samuelwhite/development-autonomy-framework)

#DeveloperTools #Python #AIEngineering

## Suggested visual and demonstration

Use [the synthetic Mission Control screenshot](mission-control-synthetic.png) with
the caption: **DAF v0.1 Developer Preview — offline, synthetic Mission Control snapshot.
No live model calls.** Keep its OFFLINE / SYNTHETIC label visible.

For a 45–60 second recording, follow the [offline walkthrough](demo.md): show the
three scenario cards, the failed attempt beside its correction, then the third-segment
budget refusal. Describe merge/deployment as not performed and distinguish the
dashboard's fixture validation from the repository's real hosted CI.

## Review decisions

- Confirm README positioning, screenshot and onboarding clarity.
- Approve or edit the description, topics and LinkedIn draft.
- Review [draft release notes](release-notes-v0.1.md) and [launch evidence](public-launch.md).
- Follow the [release checklist](release-checklist.md) for final source review and any
  separately authorised publication. This document grants no publishing authority.

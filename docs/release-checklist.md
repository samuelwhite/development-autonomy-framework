# Public release checklist

The candidate is **not publication-ready** while any BLOCKED item remains.
Evaluation success and publication approval are separate decisions.

| Status | Gate |
| --- | --- |
| PASS by construction | Explicit file allowlist; no private Git history, journals, images or CI logs |
| PASS by construction | No runtime dependencies, live adapter, remote listener or credential setup |
| WARN | Proposed public Windows/Linux matrix needs an actual run after repository creation approval |
| WARN | Dependency/advisory results age; re-run security checks on the final selected code |
| PASS | Owner confirmed personal ownership, redistribution authority and Apache-2.0; notice: Copyright 2026 Samuel James White |
| PASS | Intended repository name: development-autonomy-framework |
| BLOCKED | Owner accepts final disclosure inventory and exact distribution bytes |
| BLOCKED | Verify repository has no access to self-hosted runners or private secrets |
| BLOCKED | Confirm private security contact; verify GitHub private vulnerability reporting at approved publication |
| BLOCKED | Separate owner authorisation to create a private staging repository |
| BLOCKED | Explicit final owner approval to publish the exact reviewed release |

The private engineering review contains exact commit, test and export hashes.
It is deliberately absent from the public package because it references private
development history. Do not copy that evidence into the public repository.

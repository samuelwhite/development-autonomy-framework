# Capabilities and deliberate exclusions

| Included in v0.1 | Boundary |
| --- | --- |
| Synthetic plan validation and dependency ordering | Schema 1, no live execution policy |
| Durable milestones, attempts, correction evidence and outbox | Local synthetic SQLite journals only |
| Committed stop fencing, monotonic epochs and uncertain-operation retention | No claim that remote work or spending stopped |
| Atomic request/segment reservations and deterministic checkpoints | Built-in synthetic byte-token model and fictional prices |
| Static Mission Control demonstration | Snapshot, no authenticated service or interactive approvals |
| Standalone wheel/source packaging and adversarial fixtures | No model SDK, JavaScript dependency or runtime service |

Excluded capabilities are not silently disabled features:

- Real model transports: finite in-flight spending, cancellation, retries and
  response accounting need provider-specific evidence beyond simulated tests.
- Owner authentication, signatures and approval endpoints: production identity,
  signer separation, trust anchors and recovery ownership remain unresolved.
  Offline identity prototypes are not presented as usable authentication.
- Product-specific controllers, adapters and deployment: these carry private
  assumptions and are not necessary to evaluate the portable core.
- GitHub specification import, publication and CI reconciliation: their current
  adapters depend on private execution schemas. A public schema and transport
  contract must be reviewed before porting. Plans in this preview are local examples.
- Household notifications and remote dashboards: installation, authentication,
  routing and privacy requirements are outside this offline release.
- Private execution histories, evidence, CI captures, credentials and images:
  none are shipped. All demonstration data is synthetic.

The libraries are readable Python, not a security boundary against a developer
who can modify their own process or files. Do not connect custom workers to this
preview and describe its fixture limits as real spending guarantees.

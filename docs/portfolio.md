# Why DAF emerged from building Victoria

DAF grew from the challenges of building **Victoria**: making development plans
explicit, preserving failed attempts, recovering safely and knowing when to stop.
Those challenges raised a product question: how can an owner understand and direct
work that continues across multiple attempts?

A useful result needs more than a successful attempt. It needs a connection to the
original intent and evidence that the acceptance criteria were met. When an attempt
fails, its history still matters. When work resumes after an interruption, the owner
needs to know what has already happened and what remains uncertain.

DAF brings those concerns into a small, inspectable framework. Explicit milestones
connect work to its purpose. Durable evidence preserves failures alongside their
corrections. Recovery and stop boundaries make continuation a deliberate part of
the design. Mission Control presents that evidence so progress, unresolved decisions
and stopped work can be understood together.

The public v0.1 Developer Preview isolates these ideas in an offline demonstration
with synthetic data. It offers a way to inspect the control mechanisms without
connecting a real model or product repository. Victoria's pinned controller has not
adopted this preview, and no Victoria source or execution history is included.

Explore the [walkthrough](demo.md), [architecture](architecture.md) and
[capability boundaries](capabilities.md) to see how those product questions map to
the preview's implementation.

# ADR 001: self-contained offline desktop candidate

Status: implemented for Product review, 29 October 2026.
Baseline: `d076ee39ee3b3561cc9457d9d2988464f6788837`.

## Decision

Wrap the approved static v0.2 UI in a minimal Electron main process and distribute
a Windows x64 portable ZIP. Bundle a pinned runtime, with no runtime dependency
installation, update checks, server or permanent daemon. Keep Linux x64 as an
experimental CI target. The larger download is the principal cost of making
first launch independent of locally installed runtimes and network access.

| Option | Benefits | Costs for this milestone |
| --- | --- | --- |
| Electron + portable archive | Existing JS/HTML unchanged; packaged-window automation; Windows/Linux; no first-launch prerequisites | Bundled Chromium/Node disk and memory cost; manual security updates and signing still needed |
| Tauri + system WebView | Small app binary, typed Rust boundary | Adds Rust/native toolchains; Windows WebView2 prerequisite; OS-dependent rendering; Linux webview dependencies |
| .NET/pywebview + system WebView | Small wrapper; Python alignment for pywebview | Platform runtime/prerequisite management; native test tooling; system WebView updates outside app control |
| Fixed WebView2 runtime | Offline Windows renderer without automatic runtime updates | Microsoft documents over 250 MB of runtime binaries; Windows-specific host |
| Browser shortcut/PWA | Smallest files | Does not meet the requested ordinary desktop launch experience |

This chooses the smallest practical **dependency and implementation surface** for
a reproducibly testable offline package, not the smallest byte count. Revisit the
decision if Product prioritises download size over bundled-runtime independence.
The [WebView2 distribution documentation](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution)
explains the system-runtime versus fixed-runtime trade-off.

## Boundaries

The sandboxed, context-isolated renderer has no Node access, preload, IPC bridge,
provider SDK or credentials. An exact four-file `daf://app` protocol returns bytes
from the package without an HTTP listener. CSP forbids connections, frames,
workers and forms; session handlers block other requests, permissions and downloads;
the window rejects pop-ups, remote navigation and redirects. Chromium background
network facilities and DNS resolution are disabled for this application. No
autoUpdater, crashReporter upload or shell-opening facility is used.

These follow [Electron's security guidance](https://www.electronjs.org/docs/latest/tutorial/security)
and [custom protocol API](https://www.electronjs.org/docs/latest/api/protocol).
Network logs and adversarial packaged tests validate the observed boundary. On
some hosts Chromium performs a local IPv6 route lookup by connecting a UDP socket
to its fixed address constant and inspecting the local address; no datagram is
sent by this lookup. See `StartGloballyReachableCheck` / `FinishGloballyReachableCheck`
in [Chromium's resolver source](https://chromium.googlesource.com/chromium/src/+/HEAD/net/dns/host_resolver_manager.cc).
The audit reports these checks separately and rejects all transport sends, TCP
attempts and other UDP destinations. This is not OS-level air-gap enforcement or
proof against a compromised runtime.

The simulation remains tab/session storage. Reload demonstrates interruption;
closing clears progress and ends the process. No durable controller journal or
authority is inferred from UI state. The existing Python controller, ledger,
security gates, version and v0.1 release remain untouched.

## Later integration, separate decision

If approved later, a short-lived Python child process could speak versioned,
schema-validated messages over stdio. A minimal typed preload API would expose
named operations only, checking sender/origin, inputs and responses; the Python
controller would retain authority for approval, stop, recovery and budgets.
No renderer-supplied command, arbitrary path, generic IPC channel or local network
port should become an execution capability. This milestone implements **none** of
that bridge and makes no provider integration choice. Existing provider proposals
remain proposals. Live providers require their own review.

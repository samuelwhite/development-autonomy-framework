# DAF 0.2.1 desktop review candidate

The approved v0.2 interface in a normal application window. **Entirely simulated;
not a functional AI development controller.** No Python controller is launched.

For ordinary installation, launch, removal and recovery, read
[START-HERE.txt](START-HERE.txt). Windows users extract the portable ZIP and open
`DAF.exe`. No developer tools or administrator rights are required. This is an
unsigned Product-review candidate, not a public release. Never bypass an OS warning.

## Maintainer build

Build tools only: Node **22.12 or later** (locally validated with **24.15.0**) with
npm, Git and internet access to download
the locked npm dependencies and Electron **45.1.0**. The installed app uses none
of the developer tools and runs offline. On Windows PowerShell, from the repo:

```powershell
cd desktop
npm ci --no-fund
npm audit --audit-level=moderate
npm test
npm run build
npm run test:desktop
./archive-windows.ps1
```

Output: `dist/desktop/DAF-0.2.1-windows-x64.zip`, a SHA-256 sidecar and byte-size
metrics. The ZIP contains `DAF-win32-x64/DAF.exe` and its runtime. Keep the entire
folder. Builds are repeatable from the lockfile but ZIP timestamps mean they are
not claimed byte-for-byte reproducible. `BUILD-INFO.json` records the approved
baseline, bundled Electron version and input prototype hashes. The build copies
only named UI files plus the tiny host; it excludes Python, tests and build tools.
Only version/footer/JavaScript-error wording changes in the copied HTML.

On Linux x64 the same `npm ci`, `npm test` and `npm run build` produce
`dist/desktop/DAF-linux-x64/DAF`. Run `xvfb-run -a npm run test:desktop` on a headless
CI machine with GTK/NSS/ALSA and sandbox prerequisites. CI configures the official
setuid sandbox helper on its disposable runner; it never passes `--no-sandbox`.
An Ubuntu CI pass is not consumer Linux installation qualification.

The automated desktop suite launches the **packaged executable**, hides developer
tools from Windows PATH and runs the existing complete prototype journey suite.
It checks isolation, blocked network/file probes, close/relaunch and a Chromium
network log. Playwright's debugging endpoints exist only in test launches.
`DAF_DESKTOP_EXECUTABLE` can select a freshly extracted copy for the same tests.
Evidence screenshots and local network logs go to ignored `desktop/test-output`.
Raw network logs are not uploaded because they can contain host configuration.

The original four `preview-quality` jobs remain unchanged. The new desktop workflow
adds Windows and Ubuntu packaged tests, without creating a release, publishing to
a registry or enabling an updater. Repository policy permits only the existing
pinned checkout/setup-python Actions: desktop CI uses runner-provided Node and
writes aggregate results to its job summary. It does not change that policy or
upload packages/artifacts. Obtain the review ZIP from the maintainer's local build.

See [architecture decision](../docs/adr-001-desktop-packaging.md),
[validation evidence and limitations](../docs/v0.2.1-validation.md) and
[clean Windows acceptance](../docs/v0.2.1-clean-windows.md).

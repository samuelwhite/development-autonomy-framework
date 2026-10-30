# DAF M1.2 desktop Product-review candidate

Open DAF normally, choose **Import from GitHub**, approve one public read and
inspect a genuine commit-pinned plan. Full source snapshots survive closing and
are revalidated locally when reopened. The approved v0.2.1 offline simulation
remains separate, with all three permission modes.

**Read-only planning; not an AI development controller.** No provider, credentials,
execution, repository write, spending or automatic updates. Signing, clean Windows
acceptance and screen-reader qualification remain distribution gates.

Ordinary users follow [START-HERE.txt](START-HERE.txt): extract the complete ZIP
and open DAF.exe. Python and Electron are included. No terminal or developer tools.
Never bypass an OS security warning. No public release or binary upload.

## Maintainer build

Build-time tools only: Git, Node 22.12+, npm and OS tar. Internet access downloads
locked dependencies and checksum-pinned runtimes. Source tests additionally need
Python 3.12/3.13 and requirements-dev.txt; ordinary users do not.

```powershell
cd desktop
npm ci --no-fund
npm audit --audit-level=moderate
npm test
npm run build
# Test-only opt-in to real reads of the public DAF acceptance plan.
$env:DAF_TEST_PUBLIC_READ = '1'
npm run test:desktop
./archive-windows.ps1
```

Output: `dist/m1.2-desktop/DAF-M1.2-windows-x64.zip`, SHA-256 sidecar and metrics.
Keep the entire DAF-win32-x64 folder. The original v0.2.1 candidate is not overwritten.
Package metadata is 0.2.2-m1.2, not a tag or release. ZIP timestamps prevent a claim
of byte-reproducible archives.

The Python manifest pins 3.14.10: PSF embeddable Windows and Astral 20261026 Linux.
Builds copy six named pure DAF modules, the fixed sidecar, shared protocol and
notices. No execution engine, worker, receipt CLI, tests or user-package loading.
BUILD-INFO.json records runtime pins and original UI hashes.

Linux uses the same npm build commands. For headless Ubuntu 24.04 testing use
`xvfb-run -a npm run test:desktop` with GTK/NSS/ALSA, system CA certificates and
a working Chromium sandbox. CI configures its disposable runner's sandbox helper;
users must never use --no-sandbox or disable OS protections. Linux remains experimental.

## Validation

The four Python jobs retain lint/format, wheel/sdist installation, security tests
and strict audits. Desktop CI builds Windows/Linux packages and runs the original
simulation plus real public planning, persistence and child-lifecycle journeys.
Existing pinned Actions and read-only token permissions remain; no package upload.

CI substitutes only the native consent button response. Transport, complete-plan
validation, persistence and packaged UI are real. The separate native Windows
walkthrough exercises the actual dialog. Windows tests hide developer tools from
PATH. Public GitHub outages/rate limits must fail acceptance rather than silently
substituting fixtures. Test screenshots and summaries stay in desktop/test-output.

See [security design](../docs/adr-002-read-only-desktop-planning.md),
[walkthrough](../docs/m1.2-walkthrough.md) and
[validation and limits](../docs/m1.2-validation.md).
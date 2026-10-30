# Bundled Python provenance and notices

Retrieved 30 October 2026 from the runtime publishers, without modification:

- `python-win32.spdx.json`: [PSF Windows embeddable SBOM](https://www.python.org/ftp/python/3.14.10/python-3.14.10-embed-amd64.zip.spdx.json), SHA-256 `d448c78f5fae170303d3b022d61507155e4d30e541c32bff3a4edd2b1e8dbf47`.
- `linux-build/python/PYTHON.json` and `licenses/`: extracted from Astral's [3.14.10+20261026 x64 GNU pgo+lto full build](https://github.com/astral-sh/python-build-standalone/releases/tag/20261026), archive SHA-256 `4a2823d5deacb631e21b3c8387a1ec9be57e1b0ed37b7770e2e71cfe7b94eb94`.

The actual installed runtime archive pins are in `../python-runtime.json`. The
full Linux archive is used only to obtain upstream build metadata and license
texts; it is not included in DAF. The runtime build omits pip/site-packages,
headers, static libraries, tkinter, idlelib, ensurepip and Python test directories.
Some notices therefore cover upstream components absent from DAF's trimmed copy.
Retaining them does not imply those components are loaded or exposed by the bridge.

Runtime source and dependency build recipes are available from
[CPython v3.14.10](https://github.com/python/cpython/tree/v3.14.10) and
[python-build-standalone 20261026](https://github.com/astral-sh/python-build-standalone/tree/20261026),
including exact dependency source archives in its build configuration. DAF's own
source is in this public repository. The upstream Berkeley DB notice requires
source availability information; these public source/build references accompany
the notice. No third-party software is relicensed under DAF's license.

The PSF Windows runtime reports OpenSSL 3.5.9; its upstream Apache-2.0 notice is
also included in the retained license set. These inventories are not vulnerability
scan results. Review native runtime advisories and license obligations again before
public distribution. No public binary distribution is authorised for M1.2.

# Third-party inventory

The separate M1.2 desktop candidate bundles Electron 45.1.0 (MIT) and its
Chromium/Node dependencies. Its complete upstream `LICENSE` and
`LICENSES.chromium.html` ship beside `DAF-LICENSE` and `DAF-NOTICE`; retain them.
Desktop build/test tools (`@electron/packager` 20.3.0, BSD-2-Clause;
Playwright 1.64.1, Apache-2.0) and transitive dependencies are locked in
`desktop/package-lock.json` and are not included in `app.asar`. Electron itself
contains components under their own licences. DAF's Apache-2.0 notice does not
relicense that runtime. M1.2 additionally bundles CPython 3.14.10: the official
PSF Windows embeddable archive and Astral's 20261026 Linux standalone archive.
Exact URLs/hashes are in `desktop/python-runtime.json`. Each retains the upstream
Python license plus desktop Python notices; these are separate from DAF's license.
The inventory below describes the offline Python package, which has no third-party
runtime dependencies. Bundled desktop runtimes are a separate packaging layer.

The runtime uses Python's standard library (including its SQLite bindings).
No third-party source, fonts, images, model weights, JavaScript bundles or SDKs
are vendored. The dashboard CSS and JavaScript are project source.

Development/build tools are installed separately, not embedded in the wheel:

| Tool | Role | Upstream licence |
| --- | --- | --- |
| Hatchling | Wheel and source build backend | MIT |
| build | Build frontend | MIT |
| pytest / pytest-cov | Tests and coverage | MIT |
| HTTPX | Existing offline tests intercept its send method; no provider request | BSD-3-Clause |
| Ruff | Lint and formatting | MIT |
| pip-audit | Dependency vulnerability audit | Apache-2.0 |

All 46 development/build/audit distributions are pinned in requirements-dev.txt;
their exact versions and reported licence metadata are recorded in
[the dependency inventory](docs/development-dependencies.json). This includes
transitive packages, not just the direct tools above. They are downloaded separately
by development tooling and CI; their code and licence grants are not incorporated
into the DAF runtime wheel or source archive. Tools such as pip and Ruff may contain
their own bundled components; their upstream notices continue to apply to those
tool distributions. DAF's Apache-2.0 licence does not relicense them.

The inventory includes MPL-2.0 build/audit dependencies (certifi and pathspec),
Python Software Foundation terms (defusedxml and typing_extensions), permissive
MIT/BSD/Apache packages, and packaging's Apache-2.0 OR BSD-2-Clause choice. These
are development dependencies, not DAF-vendored code. Do not distribute an environment,
interpreter or tool bundle under the assumption that the DAF notice covers it.

Review the resolved inventory and licences at release time. A successful vulnerability
scan is not a complete licence or provenance review. Python's licence and bundled
components remain governed by the Python distribution's notices. Python is not
embedded in the wheel; it is bundled in the separate desktop candidate.

GitHub Actions checkout and setup-python are MIT-licensed upstream projects
referenced at fixed commits; their code is not copied into this package. Recheck action provenance and advisories
when reviewing future workflow changes. The approved public CI configuration is
enabled; its pinned references and permissions remain unchanged.

The [Mission Control screenshot](docs/mission-control-synthetic.jpg) captures DAF's
own dashboard with synthetic data. It contains no third-party artwork, private journals
or live provider results; see [screenshot provenance](docs/screenshot.md).

Samuel James White has confirmed personal ownership of DAF and authority to license
and redistribute the reviewed source under Apache-2.0. This confirmation does not
replace the third-party provenance and licence checks described above.

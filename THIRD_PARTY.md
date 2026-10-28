# Third-party inventory

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
tool distributions. DAF's licence, once chosen, does not relicense them.

The inventory includes MPL-2.0 build/audit dependencies (certifi and pathspec),
Python Software Foundation terms (defusedxml and typing_extensions), permissive
MIT/BSD/Apache packages, and packaging's Apache-2.0 OR BSD-2-Clause choice. These
are development dependencies, not DAF-vendored code. Do not distribute an environment,
interpreter or tool bundle under the assumption that the DAF notice covers it.

Review the resolved inventory and licences at release time. A successful vulnerability
scan is not a complete licence or provenance review. Python's licence and bundled
components remain governed by the Python distribution's notices; Python itself
is not bundled here.

GitHub Actions checkout and setup-python are MIT-licensed upstream projects
referenced at fixed commits; their code is not copied into this package. Recheck action provenance and advisories
before enabling public CI. Candidate source redistribution rights still need the
owner's confirmation even where no third-party file was found.

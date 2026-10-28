# Contributing

DAF v0.1 is an offline Developer Preview, licensed under Apache-2.0. Only contribute
material you have authority to submit under that licence. Once the repository is
public and its safeguards are verified, use Issues and pull requests for evaluation
feedback and focused changes. Public source availability is not a formal release
or a claim that live autonomous execution is supported.

Use Python 3.12+ in an isolated virtual environment, then from the repository root:

```text
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m ruff format --check .
python -m pytest --cov=daf --cov-report=term-missing
python scripts/check_distribution.py
python -m build
python scripts/smoke_wheel.py
python scripts/smoke_sdist.py
python -m pip_audit -r requirements-dev.txt --strict
```

Tests must use synthetic data. Do not add credentials, paid calls, private service
addresses, captured transcripts or real execution journals. Keep changes small;
describe the trigger, resulting behavior, tests and remaining limitations.
Tests for failure/recovery boundaries should fail if the guard is removed.

The built wheel is tested in a clean environment outside this source tree. The
smoke script uses only a local wheel after building; it does not access a provider.
Public CI runs only on GitHub-hosted runners. Never request a private runner label.

Maintainers can manually validate a reviewed ref using the `preview-quality`
workflow's `workflow_dispatch` trigger once it is on the default branch and
repository Actions is approved and enabled. Confirm the run's checkout commit
and all four Windows/Linux, Python 3.12/3.13 results. A workflow file or local pass
is not evidence that hosted validation passed. Do not enable private-repository
runs without available included allowance or use paid services.

For sensitive security findings, follow [SECURITY.md](SECURITY.md). Do not put
private reports in public Issues.

Plan changes, execution authority, merging and deployment are separate decisions.
A contribution or a green test suite cannot approve live execution.

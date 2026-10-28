# Contributing

This candidate is not published. DAF uses Apache-2.0; only contribute material you
have authority to submit under that licence. Public contributions can begin after
the owner approves publication and repository policy.

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

Plan changes, execution authority, merging and deployment are separate decisions.
A contribution or a green test suite cannot approve live execution.

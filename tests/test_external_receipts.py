"""Offline boundary tests for supplied receipts; no remote evidence verification."""
from copy import deepcopy

import pytest

from daf.contract import Refused
from daf.external_receipts import receipt_sha256, validate_external_receipt


def fixture():
    return {
        "schema_version": 1,
        "plan_sha256": "a" * 64,
        "milestone_id": "D1",
        "attempt_id": "attempt-1",
        "repository": "example/product",
        "baseline_sha": "b" * 40,
        "head_sha": "c" * 40,
        "task_sha256": "d" * 64,
        "execution": "supervised_codex",
        "checks": [
            {"name": "offline", "head_sha": "c" * 40,
             "result": "passed",
             "url": "https://github.com/example/product/actions/runs/12"}
        ],
        "pr_url": "https://github.com/example/product/pull/3",
        "status": "externally_supplied_unverified",
    }


def test_valid_receipt_is_copied_without_promoting_claims():
    original = fixture()
    output = validate_external_receipt(original)
    assert output == original
    assert output is not original
    assert output["status"] == "externally_supplied_unverified"
    assert receipt_sha256(output) == receipt_sha256(original)


@pytest.mark.parametrize("field,value", [
    ("status", "verified"),
    ("execution", "autonomous_codex"),
    ("head_sha", "wrong"),
    ("pr_url", "https://github.com/other/product/pull/3"),
    ("pr_url", "file:///tmp/secrets"),
    ("repository", "../outside"),
    ("schema_version", True),
    ("task_sha256", "z" * 64),
])
def test_invalid_claims_refused(field, value):
    record = fixture()
    record[field] = value
    with pytest.raises(Refused):
        validate_external_receipt(record)


def test_revision_mismatch_refused():
    record = fixture()
    record["checks"][0]["head_sha"] = "e" * 40
    with pytest.raises(Refused, match="receipt_revision_mismatch"):
        validate_external_receipt(record)


def test_duplicate_or_cross_repository_checks_refused():
    record = fixture()
    record["checks"].append(deepcopy(record["checks"][0]))
    with pytest.raises(Refused, match="duplicate_receipt_check"):
        validate_external_receipt(record)
    record = fixture()
    record["checks"][0]["url"] = "https://github.com/example/other/actions/runs/12"
    with pytest.raises(Refused, match="receipt_repository_mismatch"):
        validate_external_receipt(record)


def test_unexpected_fields_refused():
    record = fixture()
    record["unexpected_field"] = "test-value"
    with pytest.raises(Refused, match="invalid_receipt_fields"):
        validate_external_receipt(record)

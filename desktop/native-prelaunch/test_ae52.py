"""Portable refusal tests only. No approved packages, decisions, claims or receipts."""

import ast
import copy
import itertools
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch

import ae5_build_review as review
import ae5_parent as parent
import ae5_resources as recovery
import ae5_windows as windows
import ae51_contract as contract
import ae51_package as packages
import ae51_tc0 as entry
from ae5_contract import canonical
from test_ae51 import bound


def preflight_header():
    return {
        "schema": "daf-ae51-package/v1",
        "case": "TC-0",
        "status": "PREFLIGHT_ONLY",
        "build": "dist/not-a-build",
        "workers": "dist/not-workers",
        "binding": bound(),
        "approval": None,
        "execution_authority": False,
        "qualified": False,
    }


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.effects = [
            self.stack.enter_context(
                patch.object(
                    entry,
                    "verify_package",
                    side_effect=AssertionError("unexpected build verification"),
                )
            ),
            self.stack.enter_context(
                patch.object(
                    entry, "publish", side_effect=AssertionError("unexpected claim/evidence write")
                )
            ),
            self.stack.enter_context(
                patch.object(
                    windows,
                    "WindowsCustody",
                    side_effect=AssertionError("unexpected native adapter"),
                )
            ),
            self.stack.enter_context(
                patch("subprocess.Popen", side_effect=AssertionError("unexpected subprocess"))
            ),
        ]

    def assert_no_effects(self):
        for effect in self.effects:
            effect.assert_not_called()

    def supply_header_bytes(self, value):
        # In-memory path read only; no on-disk package or approval is created.
        fake_path = Mock()
        fake_path.read_bytes.return_value = canonical(value)
        self.stack.enter_context(patch.object(packages, "owned", return_value=fake_path))

    def test_real_public_entry_rejects_unapproved_candidate_before_subprocesses(self):
        self.supply_header_bytes(preflight_header())
        with self.assertRaisesRegex(ValueError, "preflight_is_not_approval"):
            parent.native_entry(Path("unapproved-input"))
        self.assert_no_effects()

    def test_validation_or_candidate_identifier_is_not_approval(self):
        for status in ("COMPILED_NOT_EXECUTED", "CI_PASS", "DAF-A-E5.2-TC-0-RC1", True, None):
            value = preflight_header()
            value["status"] = status
            fake_path = Mock()
            fake_path.read_bytes.return_value = canonical(value)
            with patch.object(packages, "owned", return_value=fake_path):
                with self.subTest(status=status), self.assertRaises(ValueError):
                    parent.native_entry(Path("invalid-header"))
        self.assert_no_effects()

    def test_other_cases_never_reach_native_verification(self):
        for case in (
            "TC-1",
            "TC-2",
            "TC-3",
            "TC-4",
            "TC-5",
            "TC-6",
            "TC-7",
            "TC-8",
            "A2-16",
            "A2-17",
        ):
            value = preflight_header()
            value["case"] = value["binding"]["case"] = case
            fake_path = Mock()
            fake_path.read_bytes.return_value = canonical(value)
            with patch.object(packages, "owned", return_value=fake_path):
                with self.subTest(case=case), self.assertRaisesRegex(ValueError, "package_case"):
                    parent.native_entry(Path("foreign-case"))
        self.assert_no_effects()

    def test_malformed_source_binding_or_authority_refuses_before_effects(self):
        for key, replacement in (
            ("source_commit", "wrong"),
            ("source_tree", "wrong"),
            ("manifest", "wrong"),
        ):
            value = preflight_header()
            value["binding"][key] = replacement
            fake_path = Mock()
            fake_path.read_bytes.return_value = canonical(value)
            with patch.object(packages, "owned", return_value=fake_path):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    parent.native_entry(Path("invalid-binding"))
        value = preflight_header()
        value["execution_authority"] = True
        self.supply_header_bytes(value)
        with self.assertRaisesRegex(ValueError, "no_authority"):
            parent.native_entry(Path("forged-authority"))
        self.assert_no_effects()

    def test_missing_package_refuses_before_effects(self):
        missing = packages.REPO / "dist/ae52-deliberately-missing-package.json"
        self.assertFalse(missing.exists())
        with self.assertRaises(FileNotFoundError):
            parent.native_entry(missing)
        self.assert_no_effects()

    def test_missing_approval_cannot_be_replaced_by_header_assertion(self):
        # Malformed in-memory return from the header reader, not an issued package.
        # Even an asserted reviewed status with no approval must refuse.
        invalid = preflight_header()
        invalid["status"] = "PRODUCT_RELEASE_REVIEWED"
        with patch.object(entry, "read_package", return_value=(invalid, "0" * 64)):
            with self.assertRaisesRegex(ValueError, "preflight_is_not_approval"):
                parent.native_entry(Path("not-created"))
        self.assert_no_effects()

    def test_missing_approval_bytes_refuse_before_build_verification(self):
        invalid = preflight_header()
        invalid["status"] = "PRODUCT_RELEASE_REVIEWED"
        invalid["approval"] = "dist/ae52-deliberately-missing-approval.json"
        self.assertFalse((packages.REPO / invalid["approval"]).exists())
        with patch.object(entry, "read_package", return_value=(invalid, "0" * 64)):
            with self.assertRaises(FileNotFoundError):
                parent.native_entry(Path("not-created"))
        self.assert_no_effects()

    def test_malformed_approval_bytes_cannot_start_verification(self):
        invalid = preflight_header()
        invalid["status"] = "PRODUCT_RELEASE_REVIEWED"
        invalid["approval"] = "dist/not-an-approval.json"
        fake_path = Mock()
        fake_path.read_bytes.return_value = b"{}"
        with patch.object(entry, "read_package", return_value=(invalid, "0" * 64)):
            with patch.object(entry, "owned", return_value=fake_path):
                with self.assertRaises(ValueError):
                    parent.native_entry(Path("not-created"))
        self.assert_no_effects()

    def test_foreign_candidate_decision_refuses_before_git(self):
        invalid = preflight_header()
        invalid["status"] = "PRODUCT_RELEASE_REVIEWED"
        invalid["approval"] = "dist/not-an-approval.json"
        foreign = {
            "schema": "daf-ae51-product-approval/v1",
            "case": "TC-0",
            "binding": contract.binding(bound()),
            "decision": "AUTHORISE_TC0_ONCE",
            "decision_id": "FOREIGN-NOT-APPROVED",
            "attempts": 1,
            "retries": 0,
            "not_before": 100,
            "expires": 200,
        }
        fake_path = Mock()
        fake_path.read_bytes.return_value = canonical(foreign)
        with patch.object(entry, "read_package", return_value=(invalid, "0" * 64)):
            with (
                patch.object(entry, "owned", return_value=fake_path),
                patch.object(entry.time, "time", return_value=150),
            ):
                with self.assertRaisesRegex(ValueError, "unreviewed_product_decision"):
                    parent.native_entry(Path("not-created"))
        self.assert_no_effects()

    def test_approval_binding_remains_exact_single_use_and_expiring(self):
        # Every vector is invalid. No accepted approval record is made or saved.
        invalid = {
            "schema": "daf-ae51-product-approval/v1",
            "case": "TC-0",
            "binding": "0" * 64,
            "decision": "AUTHORISE_TC0_ONCE",
            "decision_id": contract.PRODUCT_DECISION_ID,
            "attempts": 1,
            "retries": 0,
            "not_before": 100,
            "expires": 200,
        }
        with self.assertRaisesRegex(ValueError, "approval_binding"):
            contract.approval(invalid, bound(), 150)
        for key, value in (
            ("case", "TC-1"),
            ("decision", "COMPILE_PASS"),
            ("attempts", 2),
            ("retries", 1),
            ("expires", 150),
            ("not_before", 151),
        ):
            vector = copy.deepcopy(invalid)
            vector["binding"] = contract.binding(bound())
            vector[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                contract.approval(vector, bound(), 150)
        self.assert_no_effects()

    def test_approval_precedes_git_claim_and_native_adapter_in_actual_runner(self):
        tree = ast.parse(Path(entry.__file__).read_text())
        runner = next(
            n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "execute_tc0"
        )
        calls = sorted(
            (n.lineno, ast.unparse(n.func)) for n in ast.walk(runner) if isinstance(n, ast.Call)
        )
        first = {
            name: next(line for line, called in calls if called == name)
            for name in (
                "read_package",
                "contract.approval",
                "verify_package",
                "publish",
                "ae5_windows.WindowsCustody",
            )
        }
        self.assertLess(first["read_package"], first["contract.approval"])
        self.assertLess(first["contract.approval"], first["verify_package"])
        self.assertLess(first["verify_package"], first["publish"])
        self.assertLess(first["publish"], first["ae5_windows.WindowsCustody"])
        self.assertIn(
            'approval["decision_id"] == contract.PRODUCT_DECISION_ID',
            Path(entry.__file__).read_text(),
        )

    def test_build_review_accepts_only_closed_history_or_exact_tc0_candidate(self):
        closed = {
            "python": False,
            "windows": False,
            "cpp": False,
            "recovery": False,
            "decision": None,
        }
        candidate = {
            "python": True,
            "windows": True,
            "cpp": True,
            "recovery": False,
            "decision": "DAF-A-E5.2-TC-0-RC1",
        }
        self.assertEqual(review.native_source_state(closed), "CLOSED")
        self.assertEqual(
            review.native_source_state(candidate), "TC0_SOURCE_CANDIDATE_APPROVAL_REQUIRED"
        )
        self.assertEqual(contract.source_gates(Path(__file__).parent), candidate)
        for flags in itertools.product((False, True), repeat=4):
            for decision in (None, candidate["decision"], "TC-1"):
                value = dict(zip(("python", "windows", "cpp", "recovery"), flags, strict=True))
                value["decision"] = decision
                if value not in (closed, candidate):
                    with self.subTest(value=value), self.assertRaises(ValueError):
                        review.native_source_state(value)
        for wrong in (0, 1, None, "true"):
            value = {**candidate, "python": wrong}
            with self.assertRaises(ValueError):
                review.native_source_state(value)
        self.assertFalse(recovery.RECOVERY_RELEASE)


if __name__ == "__main__":
    unittest.main()

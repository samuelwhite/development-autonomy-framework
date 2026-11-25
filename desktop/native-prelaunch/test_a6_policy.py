"""Source-bound acceptance equivalence. Pure Python; no Windows/native execution."""

import hashlib
import itertools
import unittest
from pathlib import Path

import a3_observations
from test_a3 import changed, fixture

BASELINE_SHA = "8d6c2f9674b6aad75674cdae911667f584181421a9a7587021fb35c64f7ff363"
MOVED = "    for (DWORD mask : found.pipes) s.require(mask == 1 || mask == 2 || mask == 4, 116);\n"
OLD = "        s.require(mask == 1 || mask == 2 || mask == 4, 116);\n"
FOLLOWING = "        s.require(pipeSet.insert(mask).second, 117);\n"


def decision(inventory, new):
    """Row = pipe mask, any hostile match, correct binding, final comparison OK.

    Mask 7 represents every mask other than 0/1/2/4 with the same predicate
    outcome. Hostile nonzero and final comparison failures are Boolean classes.
    Snapshot preconditions are enforced before this policy in unchanged code.
    """
    if any(row[1] for row in inventory):
        return 201
    if new and any(row[0] not in (1, 2, 4) for row in inventory):
        return 116
    if len(inventory) != 3:
        return 115
    used = set()
    for mask, _, binding, comparison in inventory:
        if not new and mask not in (1, 2, 4):
            return 116
        if mask in used:
            return 117
        used.add(mask)
        if not binding:
            return 118
        if not comparison:
            return 119
    return 0


class RefusalPrecedence(unittest.TestCase):
    def test_entire_header_diff_is_exactly_the_approved_move(self):
        raw = Path(__file__).with_name("suspended-inspection.h").read_text(encoding="utf-8")
        self.assertEqual(raw.count(MOVED), 1)
        self.assertNotIn(OLD, raw)
        self.assertEqual(raw.count(FOLLOWING), 1)
        prior = raw.replace(MOVED, "").replace(FOLLOWING, OLD + FOLLOWING)
        self.assertEqual(hashlib.sha256(prior.encode()).hexdigest(), BASELINE_SHA)
        policy = raw[raw.index("inline void requireAccepted") : raw.index("inline void inspect")]
        self.assertLess(policy.index("mask == 0, 201"), policy.index(MOVED.strip()))
        self.assertLess(policy.index(MOVED.strip()), policy.index("found.values.size() == 3, 115"))

    def test_exhaustive_acceptance_equivalence_for_zero_to_three_rows(self):
        # All combinations of every Boolean predicate class; no random sampling.
        rows = tuple(
            itertools.product((0, 1, 2, 4, 7), (False, True), (False, True), (False, True))
        )
        count = accepted = 0
        for size in range(4):
            for inventory in itertools.product(rows, repeat=size):
                before, after = decision(inventory, False), decision(inventory, True)
                self.assertEqual(before == 0, after == 0)
                predicate = (
                    size == 3
                    and {row[0] for row in inventory} == {1, 2, 4}
                    and all(
                        not hostile and binding and comparison
                        for _, hostile, binding, comparison in inventory
                    )
                )
                self.assertEqual(after == 0, predicate)
                accepted += after == 0
                count += 1
        self.assertEqual(count, 65641)
        self.assertEqual(accepted, 6)

    def test_every_permutation_of_the_three_valid_objects_remains_accepted(self):
        for order in itertools.permutations((1, 2, 4)):
            inventory = [(mask, False, True, True) for mask in order]
            self.assertEqual((decision(inventory, False), decision(inventory, True)), (0, 0))

    def test_non_three_counts_can_never_become_accepted(self):
        # For every other bounded size, count check alone makes acceptance false;
        # earlier identity refusal can only reject sooner. Exercise each position.
        for size in (0, 1, 2, *range(4, 17)):
            inventory = [(1, False, True, True)] * size
            self.assertEqual((decision(inventory, False), decision(inventory, True)), (115, 115))
            for at in range(size):
                for row in ((0, False, True, True), (7, False, True, True), (1, True, True, True)):
                    altered = inventory.copy()
                    altered[at] = row
                    self.assertNotEqual(decision(altered, False), 0)
                    self.assertEqual(decision(altered, True), 201 if row[1] else 116)

    def test_precedence_and_remaining_refusals(self):
        valid = [(mask, False, True, True) for mask in (1, 2, 4)]
        self.assertEqual(decision([*valid, (0, False, True, True)], False), 115)
        self.assertEqual(decision([*valid, (0, False, True, True)], True), 116)
        self.assertEqual(decision([*valid, (0, True, True, True)], True), 201)
        self.assertEqual(decision([valid[0], valid[0], valid[2]], True), 117)
        self.assertEqual(decision([(1, False, False, True), *valid[1:]], True), 118)
        self.assertEqual(decision([(1, False, True, False), *valid[1:]], True), 119)

    def test_partial_or_ambiguous_snapshot_never_reaches_acceptance(self):
        for key, value in {
            "a3_s0_h0_checked": 254,
            "a3_s1_h1_copy_error": 6,
            "a3_s0_handle_end": 234,
            "a3_s1_entries": 2,
            "a3_s0_capture_status": 5,
            "a3_s1_policy_flags": 1,
            "a3_s0_suspend_count": 0,
            "a3_inventories_consistent": 0,
        }.items():
            with self.subTest(key=key), self.assertRaises(a3_observations.InvalidObservation):
                a3_observations.validate(changed(fixture(), key, value))


if __name__ == "__main__":
    unittest.main()

"""Closed A2 stable-inventory controls; no production authorization."""

NAMES = ("A6-12", "A6-13", "A6-14")


def specification(case):
    if case not in NAMES:
        raise ValueError("unknown_a6_case")
    sequence = NAMES.index(case) + 1
    return sequence, sequence + 11, (6, 1, 7)[sequence - 1], (4, 4, 3)[sequence - 1]

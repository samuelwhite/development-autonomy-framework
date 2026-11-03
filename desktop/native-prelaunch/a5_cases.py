"""Closed Product-authorized A2 matrix subset, in execution order."""

CASES = (
    ("A5-03", 3, 1, False),
    ("A5-04", 4, 2, False),
    ("A5-05", 5, 3, False),
    ("A5-06", 6, 4, False),
    ("A5-08", 8, 1, True),
    ("A5-09", 9, 2, True),
    ("A5-10", 10, 3, True),
    ("A5-11", 11, 4, True),
)
NAMES = tuple(case[0] for case in CASES)


def specification(case):
    if case not in NAMES:
        raise ValueError("a5_authorized_case_only")
    sequence = NAMES.index(case) + 1
    _, number, reference, alias = CASES[sequence - 1]
    return sequence, number, reference, alias

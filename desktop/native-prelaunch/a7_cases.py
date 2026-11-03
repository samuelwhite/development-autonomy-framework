"""Closed Product-authorized A7 sequence; each requires a separate invocation."""

NAMES = ("A7-C0", "A7-15")


def specification(case):
    if case not in NAMES:
        raise ValueError("a7_unknown_case")
    return (1, 0, False, 3) if case == NAMES[0] else (2, 15, True, 4)

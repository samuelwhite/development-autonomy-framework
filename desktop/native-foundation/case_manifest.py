"""Fixed maintainer acceptance inventory. Never accepts caller-selected cases."""

BAD_INPUTS = (
    ("version", "frame"),
    ("role", "frame"),
    ("oversize", "limit"),
    ("truncated", "frame"),
    ("extra", "frame"),
    ("plan", "binding"),
    ("policy", "binding"),
    ("preimage", "binding"),
    ("expected", "binding"),
    ("utf8", "text"),
    ("nul", "text"),
    ("missing", "occurrence"),
    ("duplicate", "occurrence"),
    ("source", "preimage"),
)
VERIFIER_EXTRA = (
    ("tampered", "candidate"),
    ("missing_candidate", "candidate"),
    ("extra_candidate", "candidate"),
)
CASES = (
    (("producer", "producer"), ("verifier", "verifier"), ("isolation", "probe"))
    + tuple(("producer-" + name, "producer") for name, _ in BAD_INPUTS)
    + tuple(("verifier-" + name, "verifier") for name, _ in BAD_INPUTS + VERIFIER_EXTRA)
    + tuple(
        (name, "probe") for name in ("memory", "cpu", "wall", "cancel", "leak", "overflow", "crash")
    )
    + tuple(
        (name, "probe")
        for i in range(5)
        for name in (
            (() if i == 0 else (f"cancel-repeat-{i}",)) + (f"helper-death-{i}", f"parent-death-{i}")
        )
    )
)
assert len(CASES) == 55 and len(set(CASES)) == 55

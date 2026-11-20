"""Separate A4 harness; accepted source receives only the same two hook locations."""

import sys
from pathlib import Path

import instrument_harness as a3


def instrument(raw):
    generated = a3.instrument(raw)
    for before, after in (
        (b"a3::beforeResume", b"a4::beforeResume"),
        (b"a3::FeasibilityComplete", b"a4::ControlComplete"),
        (b"a3_controlled_stop", b"a4_controlled_stop"),
    ):
        if generated.count(before) != 1:
            raise ValueError("fixture_hook_identity")
        generated = generated.replace(before, after)
    return generated


if __name__ == "__main__":
    with Path(sys.argv[2]).open("xb") as output:
        output.write(instrument(Path(sys.argv[1]).read_bytes()))

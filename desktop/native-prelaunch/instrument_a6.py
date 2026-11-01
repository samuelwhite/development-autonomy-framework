"""A6 uses the same two pinned A4 fixture hooks, with its own event namespace."""

import sys
from pathlib import Path

import instrument_fixture


def instrument(raw):
    generated = instrument_fixture.instrument(raw)
    for before, after in (
        (b"a4::beforeResume", b"a6::beforeResume"),
        (b"a4::ControlComplete", b"a6::ControlComplete"),
        (b"a4_controlled_stop", b"a6_controlled_stop"),
    ):
        if generated.count(before) != 1:
            raise ValueError("a6_fixture_hook_identity")
        generated = generated.replace(before, after)
    return generated


if __name__ == "__main__":
    with Path(sys.argv[2]).open("xb") as output:
        output.write(instrument(Path(sys.argv[1]).read_bytes()))

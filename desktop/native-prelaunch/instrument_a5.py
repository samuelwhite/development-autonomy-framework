"""A5 uses the same two pinned A4 fixture hooks, with its own event namespace."""

import sys
from pathlib import Path

import instrument_fixture


def instrument(raw):
    generated = instrument_fixture.instrument(raw)
    for before, after in (
        (b"a4::beforeResume", b"a5::beforeResume"),
        (b"a4::ControlComplete", b"a5::ControlComplete"),
        (b"a4_controlled_stop", b"a5_controlled_stop"),
    ):
        if generated.count(before) != 1:
            raise ValueError("a5_fixture_hook_identity")
        generated = generated.replace(before, after)
    return generated


if __name__ == "__main__":
    with Path(sys.argv[2]).open("xb") as output:
        output.write(instrument(Path(sys.argv[1]).read_bytes()))

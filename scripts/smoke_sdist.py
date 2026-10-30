"""Rebuild the source archive outside the checkout and test its installed wheel."""

import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]


def main():
    archives = list((ROOT / "dist").glob("*.tar.gz"))
    assert len(archives) == 1, "exactly_one_source_archive_required"
    with tempfile.TemporaryDirectory(prefix="daf-sdist-") as raw:
        directory = Path(raw)
        with tarfile.open(archives[0], "r:gz") as archive:
            for member in archive.getmembers():
                path = PurePosixPath(member.name)
                assert not path.is_absolute() and ".." not in path.parts
                assert member.isfile() or member.isdir(), "source_links_or_devices_forbidden"
                assert not {".git", ".venv", "__pycache__"}.intersection(path.parts)
            archive.extractall(directory, filter="data")
        sources = [p for p in directory.iterdir() if p.is_dir()]
        assert len(sources) == 1
        source = sources[0]
        assert (source / "scripts/smoke_wheel.py").is_file()
        assert (source / "src/daf/assets/app.js").is_file()
        # Complete-source protocol tests must remain runnable from the source archive.
        for relative in (
            "desktop/controller/service.py",
            "desktop/planning-protocol.json",
            "desktop/tests/fixtures/untrusted-snapshot.json",
            "desktop/tests/fixtures/untrusted-view.json",
        ):
            assert (source / relative).is_file(), "planning_test_dependency_missing"
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment["PYTHONNOUSERSITE"] = "1"
        subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--no-isolation"],
            cwd=source,
            env=environment,
            check=True,
            timeout=120,
        )
        subprocess.run(
            [sys.executable, "scripts/smoke_wheel.py"],
            cwd=source,
            env=environment,
            check=True,
            timeout=180,
        )
        print("Source archive rebuilt; rebuilt wheel installed and demonstrated outside checkout.")


if __name__ == "__main__":
    main()

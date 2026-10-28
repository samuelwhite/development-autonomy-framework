"""Install the built wheel with no index, then run it outside the source tree."""

import json
import os
import subprocess
import tempfile
import venv
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    wheels = list((ROOT / "dist").glob("*.whl"))
    assert len(wheels) == 1, "exactly_one_wheel_required"
    with zipfile.ZipFile(wheels[0]) as archive:
        assert "daf/examples/plan.json" in archive.namelist()
        assert "daf/assets/app.js" in archive.namelist()
        assert not any(n.startswith(("tests/", ".git/")) for n in archive.namelist())
        metadata = archive.read(next(n for n in archive.namelist() if n.endswith("/METADATA")))
        assert b"Requires-Dist:" not in metadata
        assert b"License-Expression: Apache-2.0" in metadata
        assert b"License-File: LICENSE" in metadata
        assert b"License-File: NOTICE" in metadata
        for name in ("LICENSE", "NOTICE"):
            entry = next(n for n in archive.namelist() if n.endswith("/licenses/" + name))
            assert archive.read(entry) == (ROOT / name).read_bytes()
    with tempfile.TemporaryDirectory(prefix="daf-wheel-") as raw:
        directory = Path(raw)
        venv.EnvBuilder(with_pip=True).create(directory / "env")
        python = directory / "env" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment["PYTHONNOUSERSITE"] = "1"
        subprocess.run(
            [str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheels[0])],
            cwd=directory,
            env=environment,
            check=True,
            timeout=120,
        )
        subprocess.run(
            [str(python), "-I", "-m", "daf", "demo", "--output", "demonstration"],
            cwd=directory,
            env=environment,
            check=True,
            timeout=60,
            stdout=subprocess.DEVNULL,
        )
        report = json.loads((directory / "demonstration/demonstration.json").read_text())
        assert report["provider_requests"] == 0
        assert report["progression"]["known_actual_tokens"] == 400
        print(
            json.dumps(
                {
                    "wheel_install": "passed",
                    "outside_source_tree": True,
                    "runtime_dependencies": 0,
                    "provider_requests": 0,
                }
            )
        )


if __name__ == "__main__":
    main()

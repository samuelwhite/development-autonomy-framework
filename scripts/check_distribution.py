"""Validate the standalone runtime's dependency and capability boundary."""

import ast
import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {"subprocess", "socket", "http", "urllib", "httpx", "requests", "webbrowser"}


def main():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["dependencies"] == []
    assert project["license"] == "Apache-2.0"
    assert project["license-files"] == ["LICENSE", "NOTICE"]
    assert "Copyright 2026 Samuel James White" in (ROOT / "NOTICE").read_text()
    count = 0
    for path in (ROOT / "src/daf").rglob("*.py"):
        count += 1
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom) and node.level:
                    continue
                names = (
                    [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
                )
                for name in names:
                    head = name.split(".")[0]
                    assert head in sys.stdlib_module_names and head not in FORBIDDEN, (
                        path.name,
                        head,
                    )
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"eval", "exec", "__import__"}
    assert not (ROOT / "package.json").exists()
    print(
        json.dumps(
            {
                "runtime_modules_checked": count,
                "runtime_dependencies": 0,
                "live_transport": "absent",
                "licence": project["license"],
            }
        )
    )


if __name__ == "__main__":
    main()

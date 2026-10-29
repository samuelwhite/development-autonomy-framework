"""The separate UI experiment must not introduce live transport or change the runtime."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototype"


def test_browser_boundary_has_no_external_resources_or_transport():
    # Source archives intentionally exclude this separately reviewed concept.
    if not PROTOTYPE.exists():
        pytest.skip("UI prototype is source-checkout-only")
    html = (PROTOTYPE / "index.html").read_text(encoding="utf-8")
    assert "connect-src 'none'" in html
    assert "form-action 'none'" in html
    assert "object-src 'none'" in html
    assert "SIMULATED" in html
    assert not re.search(r'(?:src|href)=["\']https?://', html)
    for name in ("app.js", "simulation.js", "style.css"):
        source = (PROTOTYPE / name).read_text(encoding="utf-8")
        assert not re.search(
            r"\b(fetch|XMLHttpRequest|WebSocket|EventSource|sendBeacon|Worker|eval)\s*\(",
            source,
        )
        assert not re.search(r"https?://|@import|url\(", source)


def test_ui_state_machine_in_node():
    if not PROTOTYPE.exists():
        pytest.skip("UI prototype is source-checkout-only")
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is optional for developers; required to run UI fixture tests")
    result = subprocess.run(
        [node, "--test", str(PROTOTYPE / "simulation.test.cjs")],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

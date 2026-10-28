"""Offline tests of the opt-in public GitHub sidecar; no real network calls."""

import base64
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from daf.contract import Refused

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/github_public_ingest.py"
spec = importlib.util.spec_from_file_location("github_public_ingest_script", SCRIPT)
sidecar = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sidecar)

REPO = "samuelwhite/development-autonomy-framework"
COMMIT = "7b24b7ce84eb7a44d2179adcbd77c17d3bda8b52"
SOURCE = "src/daf/examples/planning/public-m1.json"


class FakeResponse:
    def __init__(self, body=b"{}", status=200, content_type="application/json"):
        self._body = body
        self.status = status
        self._type = content_type

    def getheader(self, name, default=None):
        return self._type if name == "Content-Type" else default

    def read(self, count):
        return self._body[:count]


class FakeConnection:
    created = []
    response = FakeResponse()

    def __init__(self, host, timeout):
        self.created.append(self)
        self.host = host
        self.timeout = timeout
        self.calls = []
        self.closed = False

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


def test_reader_fixed_host_get_no_auth_or_redirect(monkeypatch):
    FakeConnection.created = []
    FakeConnection.response = FakeResponse(b'{"sha":"abc"}')
    monkeypatch.setattr(sidecar.http.client, "HTTPSConnection", FakeConnection)
    value = sidecar.get_public_github_json("/repos/example/product/git/commits/" + "a" * 40)
    assert value == {"sha": "abc"}
    client = FakeConnection.created[-1]
    assert client.host == "api.github.com" and client.timeout == 8
    assert client.closed is True
    (verb, path), kwargs = client.calls[0]
    assert verb == "GET" and path.startswith("/repos/")
    assert "Authorization" not in kwargs["headers"]
    FakeConnection.response = FakeResponse(status=302)
    with pytest.raises(Refused, match="public_github_read_failed"):
        sidecar.get_public_github_json("/repos/example/product/git/commits/" + "a" * 40)
    assert FakeConnection.created[-1].closed is True


def test_reader_rejects_non_json_and_excess_data(monkeypatch):
    monkeypatch.setattr(sidecar.http.client, "HTTPSConnection", FakeConnection)
    FakeConnection.response = FakeResponse(content_type="text/plain")
    with pytest.raises(Refused, match="unexpected_github_content_type"):
        sidecar.get_public_github_json("/repos/example/product/git/commits/" + "a" * 40)
    FakeConnection.response = FakeResponse(body=b" " * (sidecar.MAX_RESPONSE + 1))
    with pytest.raises(Refused, match="github_response_too_large"):
        sidecar.get_public_github_json("/repos/example/product/git/commits/" + "a" * 40)


def test_cli_requires_public_network_opt_in(monkeypatch, tmp_path, capsys):
    def no_network(_path):
        raise AssertionError("Network access without opt-in")

    monkeypatch.setattr(sidecar, "get_public_github_json", no_network)
    args = [
        "--repository",
        REPO,
        "--commit",
        COMMIT,
        "--path",
        SOURCE,
        "--milestone",
        "F1",
        "--output-dir",
        str(tmp_path),
    ]
    assert sidecar.main(args) == 2
    assert json.loads(capsys.readouterr().out)["reason"] == "explicit_public_read_required"


def test_cli_repeat_is_idempotent(monkeypatch, tmp_path, capsys):
    raw = (ROOT / SOURCE).read_bytes()
    blob_sha = hashlib.sha1(
        b"blob " + str(len(raw)).encode() + b"\0" + raw, usedforsecurity=False
    ).hexdigest()

    def read(path):
        if "/git/commits/" in path:
            return {"sha": COMMIT}
        return {
            "type": "file",
            "path": SOURCE,
            "size": len(raw),
            "encoding": "base64",
            "content": base64.b64encode(raw).decode(),
            "sha": blob_sha,
        }

    monkeypatch.setattr(sidecar, "get_public_github_json", read)
    args = [
        "--repository",
        REPO,
        "--commit",
        COMMIT,
        "--path",
        SOURCE,
        "--milestone",
        "F1",
        "--output-dir",
        str(tmp_path),
        "--public-read",
    ]
    assert sidecar.main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["outcome"] == "created" and first["execution_authority"] is False
    assert sidecar.main(args) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["outcome"] == "already_present"
    assert second["ingestion_id"] == first["ingestion_id"]
    assert len(list(tmp_path.glob("*.json"))) == 1

import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from daf.contract import Refused, digest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import live_document_pilot as live  # noqa: E402
from document_pilot import pilot_branch  # noqa: E402
from homeci_candidate import WORKFLOW_FILE  # noqa: E402
from rehearse_document_pilot import (  # noqa: E402
    DAF,
    FORGE,
    JOB_ID,
    PR,
    REVISION,
    RUN,
    RehearsalTransport,
    git,
    setup,
)


class LocalGitHub:
    def __init__(self, rehearsal, branch, pilot):
        self.rehearsal = rehearsal
        self.branch = branch
        self.pilot = pilot

    def request(self, path, payload=None):
        if payload is None:
            query = urlsplit(path)
            if query.path == f"/repos/{DAF}/pulls":
                assert parse_qs(query.query) == {
                    "state": ["all"],
                    "head": [f"{DAF.split('/')[0]}:{self.branch}"],
                    "per_page": ["2"],
                }
                return self.rehearsal.pulls(DAF, self.branch)
            return self.rehearsal.get(path)
        if path == f"/repos/{DAF}/pulls":
            assert payload["base"] == "main"
            assert payload["head"] == self.branch
            assert payload["draft"] is True
            assert payload["maintainer_can_modify"] is False
            assert self.rehearsal.branch(DAF, self.branch) == self.pilot["candidate_sha"]
            return self.rehearsal.create_draft(DAF, self.branch)
        assert path == f"/repos/{FORGE}/actions/workflows/{WORKFLOW_FILE}/dispatches"
        assert payload == {
            "ref": "main",
            "inputs": {
                "task_sha256": self.pilot["task_sha256"],
                "candidate_pr": str(PR),
                "candidate_sha": self.pilot["candidate_sha"],
                "expected_forge_sha": REVISION,
            },
        }
        return self.rehearsal.dispatch(
            {
                **self.pilot["verification"],
                "task_sha256": self.pilot["task_sha256"],
                "candidate_pr": PR,
                "candidate_sha": self.pilot["candidate_sha"],
            }
        )


@pytest.fixture
def live_fixture(tmp_path, monkeypatch):
    repo, remote, journal, (task, edit, review, pilot) = setup(tmp_path)
    branch = pilot_branch(DAF, task["request"]["attempt_id"])
    state = tmp_path / "github-state.json"
    approval = {"schema_version": 1, "repository": DAF, "journal": str(journal), "pilot": pilot}
    remote_url = live.github_url(DAF)
    assert remote_url == f"https://github.com/{DAF}.git"
    allowed = live.GIT_CONFIG
    monkeypatch.setattr(
        live,
        "GIT_CONFIG",
        tuple(
            "protocol.file.allow=always" if item == "protocol.https.allow=always" else item
            for item in allowed
        ),
    )
    monkeypatch.setattr(live, "github_url", lambda repository: Path(remote).as_uri())
    return repo, remote, task, edit, review, approval, branch, state


@pytest.mark.parametrize("loss", ["branch", "draft", "dispatch"])
def test_live_transport_recovers_once(live_fixture, monkeypatch, loss):
    repo, remote, task, edit, review, approval, branch, state = live_fixture
    publish_calls = []
    real_git = live.GitHubPilotTransport.remote_git

    def lose_branch_response(transport, *args):
        result = real_git(transport, *args)
        if args[0] != "push":
            return result
        publish_calls.append(args)
        assert args[1:] == (
            "--no-verify",
            f"--force-with-lease=refs/heads/{branch}:",
            Path(remote).as_uri(),
            f"{approval['pilot']['candidate_sha']}:refs/heads/{branch}",
        )
        assert result.returncode == 0, result.stderr
        return subprocess.CompletedProcess(args, 128) if loss == "branch" else result

    monkeypatch.setattr(live.GitHubPilotTransport, "remote_git", lose_branch_response)
    approval_digest = digest(approval)

    def invoke(simulator):
        api = LocalGitHub(simulator, branch, approval["pilot"]).request
        return live.execute(repo, task, edit, review, approval, approval_digest, api=api)

    first = RehearsalTransport(repo, remote, state, loss="uncertain-" + loss)
    result = invoke(first)
    if loss != "branch":
        reason = {"draft": "draft_create_outcome_unknown", "dispatch": "dispatch_outcome_unknown"}
        assert result["state"] == "blocked" and result["reason"] == reason[loss]
        still_hidden = RehearsalTransport(repo, remote, state)
        still_hidden.hidden.add(loss)
        assert invoke(still_hidden)["reason"] == reason[loss]
    recovered = RehearsalTransport(repo, remote, state)
    result = invoke(recovered)
    assert result["state"] == "review" and result["conclusion"] == "success"
    assert result["candidate_sha"] == approval["pilot"]["candidate_sha"]
    assert (result["draft_pr"], result["run_id"], result["run_attempt"], result["job_id"]) == (
        PR,
        RUN,
        1,
        JOB_ID,
    )
    assert invoke(RehearsalTransport(repo, remote, state)) == result
    assert len(publish_calls) == 1
    assert recovered.data["writes"] == {"branch": 0, "draft": 1, "dispatch": 1}


def test_live_transport_does_not_overwrite_a_concurrently_published_branch(
    live_fixture, monkeypatch
):
    repo, remote, task, edit, review, approval, branch, state = live_fixture
    base = task["request"]["baseline_sha"]
    simulator = RehearsalTransport(repo, remote, state)
    api = LocalGitHub(simulator, branch, approval["pilot"]).request
    real_git = live.GitHubPilotTransport.remote_git

    def race(transport, *args):
        if args[0] == "push":
            git(repo, "push", str(remote), f"{base}:refs/heads/{branch}")
        return real_git(transport, *args)

    monkeypatch.setattr(live.GitHubPilotTransport, "remote_git", race)
    result = live.execute(repo, task, edit, review, approval, digest(approval), api=api)
    assert result["state"] == "blocked" and result["reason"] == "candidate_branch_conflict"
    assert simulator.branch(DAF, branch) == base
    assert not state.exists()


def test_live_approval_binds_the_single_journal_before_any_remote_call(live_fixture):
    repo, _, task, edit, review, approval, _, _ = live_fixture
    changed = deepcopy(approval)
    changed["journal"] += "-new"
    with pytest.raises(Refused, match="live_approval_digest_changed"):
        live.execute(repo, task, edit, review, changed, digest(approval), api=None)

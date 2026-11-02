"""Read-only frozen package verification and non-authoritative preflight packaging."""

import argparse
import subprocess
from pathlib import Path

from ae5_build_review import review
from ae5_contract import canonical, exact, require
from ae51_contract import binding, digest, load

REPO = Path(__file__).resolve().parents[2]
WORKERS = {
    "producer.exe": "be7b85e698f278e74cf94138385ba9d0990d8045eae2e8d833d580de245b6ed0",
    "verifier.exe": "34bd5f3612790adb40155c9dde74785bf4527382a15be15e076315d7584f1850",
}


def identity(path):
    raw = path.read_bytes()
    return {"bytes": len(raw), "sha256": digest(raw)}


def owned(path):
    path = Path(path).absolute()
    require(path.is_relative_to(REPO / "dist"), "owned_dist_path")
    for part in (path, *path.parents):
        require(not part.is_symlink() and not part.is_junction(), "linked_package_path")
    require(path.resolve() == path, "canonical_package_path")
    return path


def frozen_sources(build, manifest):
    """One Git batch: every tracked native source, not just selected entry files."""
    commit = manifest["source_commit"]
    listing = (
        subprocess.check_output(
            [
                "git",
                "ls-tree",
                "-r",
                commit,
                "--",
                "desktop/native-prelaunch",
                "desktop/native-foundation",
            ],
            cwd=REPO,
        )
        .decode()
        .splitlines()
    )
    entries = [line.split("\t", 1) for line in listing]
    blobs = [header.split()[2] for header, _ in entries]
    batch = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=REPO,
        input=("\n".join(blobs) + "\n").encode(),
        capture_output=True,
        check=True,
    ).stdout
    at, checked = 0, {}
    for (_, name), blob in zip(entries, blobs, strict=True):
        end = batch.index(b"\n", at)
        actual, kind, length = batch[at:end].split()
        require(actual.decode() == blob and kind == b"blob", "source_blob_binding")
        length = int(length)
        raw = batch[end + 1 : end + 1 + length]
        at = end + length + 2
        frozen = build / "source" / name.removeprefix("desktop/")
        require(frozen.read_bytes().replace(b"\r\n", b"\n") == raw, "frozen_git_source")
        require((REPO / name).read_bytes().replace(b"\r\n", b"\n") == raw, "active_source_drift")
        checked[name] = digest(raw)
    require(at == len(batch), "source_batch_complete")
    tree = (
        subprocess.check_output(["git", "rev-parse", commit + "^{tree}"], cwd=REPO).decode().strip()
    )
    require(tree == manifest["source_tree"], "source_tree")
    return checked


def verify_build(build, workers):
    build, workers = owned(build), owned(workers)
    raw = (build / "build-manifest.json").read_bytes()
    manifest = load(raw)
    require(
        manifest["schema"] == "daf-ae5-compile-only/v1"
        and manifest["status"] == "COMPILED_NOT_EXECUTED"
        and manifest["failure"] is None,
        "compile_status",
    )
    require(
        manifest["native_executions"] == manifest["native_claims"] == 0
        and manifest["qualified"] is False
        and manifest["execution_authority"] is False,
        "compile_only_evidence",
    )
    for name, expected in manifest["files"].items():
        path = owned(build / name)
        require(path.is_relative_to(build) and identity(path) == expected, "manifest_file")
    sources = frozen_sources(build, manifest)
    checked = review(build, compiled=True)
    require(checked == load((build / "ae5-build-review.json").read_bytes()), "inverse_readback")
    require(
        manifest["native_gate"] == checked["native_gate"]
        and manifest["source_gates"] == checked["source_gates"]
        and checked["source_gates"]["recovery"] is False,
        "frozen_gate_evidence",
    )
    for name, expected in checked["compiler_inputs"].items():
        require(identity(Path(name)) == expected, "compiler_input_drift")
    files = {
        name: identity(build / name)
        for name in (
            "ae5-fixture-host.exe",
            "handle-probe.exe",
            "ae5-fixture-host.cpp",
            "ae5-fixture-harness.h",
        )
    }
    for name, expected in WORKERS.items():
        files[name] = identity(workers / name)
        require(files[name]["sha256"] == expected, "accepted_worker_identity")
    return manifest, digest(raw), files, sources


def verify_package(path):
    raw = owned(path).read_bytes()
    value = load(raw)
    exact(
        value,
        (
            "schema",
            "case",
            "status",
            "build",
            "workers",
            "binding",
            "approval",
            "execution_authority",
            "qualified",
        ),
    )
    require(value["schema"] == "daf-ae51-package/v1" and value["case"] == "TC-0", "package_case")
    require(value["qualified"] is False and value["execution_authority"] is False, "no_authority")
    require(value["status"] in {"PREFLIGHT_ONLY", "PRODUCT_RELEASE_REVIEWED"}, "package_status")
    manifest, manifest_sha, files, sources = verify_build(
        REPO / value["build"], REPO / value["workers"]
    )
    bound = value["binding"]
    binding(bound)
    require(
        bound["source_commit"] == manifest["source_commit"]
        and bound["source_tree"] == manifest["source_tree"]
        and bound["manifest"] == manifest_sha
        and bound["files"] == files,
        "package_build_binding",
    )
    return value, digest(raw), sources


def preflight(build, workers, output):
    """Creates a preflight package only: never an approval, consumed claim or receipt."""
    build, workers, output = owned(build), owned(workers), owned(output)
    manifest, manifest_sha, files, _ = verify_build(build, workers)
    exercise = digest(canonical({"manifest": manifest_sha, "case": "TC-0"}))[:32]
    bound = {
        "case": "TC-0",
        "source_commit": manifest["source_commit"],
        "source_tree": manifest["source_tree"],
        "manifest": manifest_sha,
        "files": files,
        "exercise": exercise,
    }
    binding(bound)
    value = {
        "schema": "daf-ae51-package/v1",
        "case": "TC-0",
        "status": "PREFLIGHT_ONLY",
        "build": build.relative_to(REPO).as_posix(),
        "workers": workers.relative_to(REPO).as_posix(),
        "binding": bound,
        "approval": None,
        "execution_authority": False,
        "qualified": False,
    }
    with output.open("xb") as stream:
        stream.write(canonical(value) + b"\n")
    verify_package(output)
    return value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compile-only TC-0 package; never executes")
    parser.add_argument("build")
    parser.add_argument("workers")
    parser.add_argument("output")
    args = parser.parse_args()
    result = preflight(args.build, args.workers, args.output)
    print(
        "PREFLIGHT_ONLY; native attempts=0; approval absent; binding=" + binding(result["binding"])
    )

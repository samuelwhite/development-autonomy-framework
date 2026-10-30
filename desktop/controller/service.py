"""One typed planning operation. No provider, command, credential or server interface."""

import http.client
import json
import re
import ssl
import time
from pathlib import Path

from daf.contract import Refused, require
from daf.github_planning import (
    MAX_RESPONSE,
    _document_response,
    read_public_document,
    validate_public_github_path,
)
from daf.planning_snapshot import (
    history,
    make_snapshot,
    project_snapshot,
    read_snapshot,
    save_snapshot,
    validate_source,
)

SCHEMA = json.loads((Path(__file__).parent.parent / "planning-protocol.json").read_text())
MAX_INPUT = 4096
MAX_OUTPUT = 1024 * 1024


def validate(value, rule):
    """The deliberately small JSON Schema subset also implemented by main."""
    if "$ref" in rule:
        return validate(value, SCHEMA["$defs"][rule["$ref"].split("/")[-1]])
    if "oneOf" in rule:
        matches = 0
        for branch in rule["oneOf"]:
            try:
                validate(value, branch)
                matches += 1
            except Refused:
                pass
        require(matches == 1, "invalid_request")
        return
    if "const" in rule:
        require(type(value) is type(rule["const"]) and value == rule["const"], "invalid_request")
    if "enum" in rule:
        require(any(type(value) is type(v) and value == v for v in rule["enum"]), "invalid_request")
    kind = rule.get("type")
    if kind == "object":
        require(isinstance(value, dict), "invalid_request")
        fields = rule.get("properties", {})
        require(set(rule.get("required", [])) <= set(value), "invalid_request")
        require(
            rule.get("minProperties", 0) <= len(value) <= rule.get("maxProperties", 1000),
            "invalid_request",
        )
        for key, item in value.items():
            if "propertyNames" in rule:
                validate(key, rule["propertyNames"])
            if key in fields:
                validate(item, fields[key])
            else:
                extra = rule.get("additionalProperties", False)
                require(isinstance(extra, dict), "invalid_request")
                validate(item, extra)
    elif kind == "array":
        require(
            isinstance(value, list) and rule.get("minItems", 0) <= len(value) <= rule["maxItems"],
            "invalid_request",
        )
        for item in value:
            validate(item, rule["items"])
    elif kind == "string":
        require(
            isinstance(value, str) and rule.get("minLength", 0) <= len(value) <= rule["maxLength"],
            "invalid_request",
        )
        require(
            "pattern" not in rule or re.fullmatch(rule["pattern"], value) is not None,
            "invalid_request",
        )
    elif kind == "integer":
        require(
            type(value) is int and rule["minimum"] <= value <= rule["maximum"], "invalid_request"
        )


class PublicReader:
    def __init__(self):
        self.deadline = time.monotonic() + 30
        self.requests = 0

    def __call__(self, path):
        validate_public_github_path(path)
        remaining = self.deadline - time.monotonic()
        require(remaining > 0, "github_timeout")
        self.requests += 1
        require(self.requests <= 18, "github_response_refused")
        # Default certificate verification; no proxy, user config, credentials or redirects.
        context = ssl.create_default_context()
        connection = http.client.HTTPSConnection(
            "api.github.com", timeout=min(8, remaining), context=context
        )
        try:
            connection.request(
                "GET",
                path,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "DAF-read-only-planning/1",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            response = connection.getresponse()
            if response.status == 404:
                raise Refused("github_not_found")
            if response.status in (403, 429):
                raise Refused("github_rate_limited")
            require(response.status == 200, "github_unavailable")
            require(
                response.getheader("Content-Type", "").split(";")[0].strip().lower()
                == "application/json",
                "github_response_refused",
            )
            raw = response.read(MAX_RESPONSE + 1)
            require(len(raw) <= MAX_RESPONSE, "github_response_refused")
            require(time.monotonic() <= self.deadline, "github_timeout")
            return _document_response(raw)
        except ssl.SSLError:
            raise Refused("github_tls_failed") from None
        except TimeoutError:
            raise Refused("github_timeout") from None
        except (OSError, http.client.HTTPException):
            raise Refused("github_unavailable") from None
        finally:
            connection.close()


def perform(request, folder, reader=None):
    validate(request, SCHEMA["$defs"]["request"])
    operation = request["operation"]
    if operation == "planning.importPublicPlan":
        source = validate_source(request["source"])
        provenance, content, _plan, _bundles = read_public_document(
            source["repository"],
            source["commit_sha"],
            source["path"],
            get_json=reader or PublicReader(),
        )
        snapshot = make_snapshot(source, content)
        require(snapshot["source"] == provenance, "snapshot_conflict")
        view = project_snapshot(snapshot)
        # Refuse unsupported display shapes before publishing any local snapshot.
        validate(view, SCHEMA["$defs"]["snapshot"])
        result = {
            "outcome": save_snapshot(folder, snapshot),
            "snapshot": view,
        }
    elif operation == "planning.getImport":
        result = {
            "outcome": "loaded",
            "snapshot": project_snapshot(read_snapshot(folder, request["id"])),
        }
    else:
        result = {"outcome": "listed", **history(folder)}
    response = {"protocol": 1, "requestId": request["requestId"], **result}
    validate(response, SCHEMA["$defs"]["response"])
    return response


def safe_error(error, operation):
    reason = str(error) if isinstance(error, Refused) else ""
    if reason in {
        "github_unavailable",
        "github_not_found",
        "github_rate_limited",
        "github_tls_failed",
        "github_timeout",
        "github_response_refused",
        "storage_limit",
        "snapshot_conflict",
    }:
        return reason
    if isinstance(error, OSError) or "storage" in reason:
        return "storage_unavailable"
    if operation == "planning.getImport":
        return "corrupted_snapshot"
    if operation == "planning.importPublicPlan":
        return "invalid_plan"
    return "invalid_request"

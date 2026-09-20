"""Privacy-gated telemetry for workflow installations."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_GITHUB_API_BASE = "https://api.github.com"
_REQUEST_TIMEOUT = 5


def is_public_repository(owner: str, repo: str) -> bool:
    """Return True iff the GitHub repository is publicly visible.

    Calls GET /repos/{owner}/{repo} without authentication. Public repos
    return 200; private and non-existent repos return 404. Returns False
    on any error (including 401, 403 rate limits, network drops, and timeouts)
    so telemetry is always skipped safely on failure.
    """
    url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}"
    headers = {"Accept": "application/vnd.github+json"}

    request = Request(url, headers=headers)  # noqa: S310
    try:
        with urlopen(request, timeout=_REQUEST_TIMEOUT) as response:  # noqa: S310
            data = json.loads(response.read())
            return not data.get("private", True)
    except (HTTPError, URLError, OSError, json.JSONDecodeError, KeyError):
        return False


def build_telemetry_payload(
    workflow_name: str,
    action: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct the enriched telemetry event payload."""
    payload: dict[str, Any] = {
        "workflow_name": workflow_name,
        "action": action,
    }
    if metadata is not None:
        payload["metadata"] = metadata
    return payload


def track_installation(
    source: str,
    workflow_name: str,
    version: str | None,
    event_type: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Emit a telemetry event for a workflow installation.

    ``event_type`` is ``"install"`` (first lock-file entry) or
    ``"updated"`` (subsequent installs where the workflow changed).

    ``metadata`` contains optional enriched workflow metadata (title,
    description, tags, icon, owner, version, source, created_at).

    This stub receives the enriched event and will be connected to the
    live telemetry endpoint in Issue #57. Only called when the registry
    repository is confirmed public.
    """
    _ = build_telemetry_payload(
        workflow_name=workflow_name,
        action=event_type,
        metadata=metadata,
    )

"""Privacy-gated telemetry for workflow installations."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_GITHUB_API_BASE = "https://api.github.com"
_REQUEST_TIMEOUT = 5


def is_public_repository(owner: str, repo: str) -> bool:
    """Return True iff the GitHub repository is publicly visible.

    Calls GET /repos/{owner}/{repo} without authentication. Public repos
    return 200; private and non-existent repos return 404. Returns False
    on any error so telemetry is always skipped safely on failure.
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


def track_installation(
    source: str,
    workflow_name: str,
    version: str | None,
    event_type: str,
) -> None:
    """Emit a telemetry event for a workflow installation.

    ``event_type`` is ``"install"`` (first lock-file entry) or
    ``"updated"`` (subsequent installs where the workflow changed).

    This is a stub. Only called when the registry repository is confirmed public.
    """

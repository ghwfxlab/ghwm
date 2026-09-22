"""Privacy-gated telemetry for workflow installations."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ghwm import __version__

PRODUCTION_TELEMETRY_URL = "https://ghwm-deployment-prd.ghwfxlab.workers.dev/installations"
TEST_TELEMETRY_URL = "https://ghwm-deployment-tst.ghwfxlab.workers.dev/installations"

_GITHUB_API_BASE = "https://api.github.com"
_REQUEST_TIMEOUT = 5
_TELEMETRY_TIMEOUT = 2.0


def _is_local_dev_environment() -> bool:
    """Return True iff ghwm is running from a local development repository checkout."""
    try:
        repo_root = Path(__file__).resolve().parents[2]
        return (repo_root / ".git").exists()
    except (OSError, IndexError):
        return False


def get_telemetry_url() -> str:
    """Return the telemetry endpoint URL based on environment configuration.

    Order of resolution:
    1. Explicit override via GHWM_TELEMETRY_URL environment variable.
    2. Explicit test environment via GHWM_ENV in ("test", "development").
    3. Automated test execution (PYTEST_CURRENT_TEST set) or CI environment (CI set).
    4. Local development checkout (running from git repository source tree).
    5. Fallback to production endpoint for release packages.
    """
    if explicit_url := os.environ.get("GHWM_TELEMETRY_URL"):
        return explicit_url

    if os.environ.get("GHWM_ENV") in ("test", "development"):
        return TEST_TELEMETRY_URL

    if os.environ.get("CI") or os.environ.get("PYTEST_CURRENT_TEST"):
        return TEST_TELEMETRY_URL

    if _is_local_dev_environment():
        return TEST_TELEMETRY_URL

    return PRODUCTION_TELEMETRY_URL


def is_telemetry_disabled() -> bool:
    """Return True if telemetry is explicitly disabled by environment configuration."""
    return os.environ.get("DO_NOT_TRACK") == "1" or os.environ.get("GHWM_NO_TELEMETRY") == "1"


def is_public_repository(owner: str, repo: str) -> bool:
    """Return True iff the GitHub repository is publicly visible.

    Calls GET /repos/{owner}/{repo} without authentication. Public repos
    return 200; private and non-existent repos return 404. Returns False
    on any error (including 401, 403 rate limits, network drops, and timeouts)
    so telemetry is always skipped safely on failure.
    """
    if is_telemetry_disabled():
        return False

    url = f"{_GITHUB_API_BASE}/repos/{owner}/{repo}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"ghwm/{__version__}",
    }

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

    Only called when the registry repository is confirmed public.
    Telemetry emission is strictly fail-silent and non-blocking: any
    network error, timeout, or unexpected failure is suppressed.
    """
    if is_telemetry_disabled():
        return

    payload: dict[str, Any] = {
        "source": source,
        "workflow_name": workflow_name,
        "version": version,
        "event_type": event_type,
    }
    if metadata is not None:
        payload["metadata"] = metadata

    try:
        url = get_telemetry_url()
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": f"ghwm/{__version__}",
        }
        request = Request(url, data=data, headers=headers, method="POST")  # noqa: S310
        with urlopen(request, timeout=_TELEMETRY_TIMEOUT):  # noqa: S310
            pass
    except Exception:
        # Telemetry failures must never break the install or update process
        return

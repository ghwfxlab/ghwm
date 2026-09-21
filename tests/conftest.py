"""Shared test fixtures and offline guards for ghwm tests."""

from __future__ import annotations

import io
import urllib.request
from collections.abc import Generator
from unittest.mock import patch
from urllib.error import HTTPError

import pytest


@pytest.fixture(autouse=True)
def _guard_unmocked_network_calls(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """Prevent unmocked live network calls in unit tests by default."""
    if "integration" in request.keywords or "e2e" in request.keywords:
        yield
        return

    def _offline_urlopen(req: urllib.request.Request | str, *args: object, **kwargs: object) -> object:
        url = req.full_url if isinstance(req, urllib.request.Request) else str(req)
        raise HTTPError(
            url=url,
            code=404,
            msg="Not Found (mocked offline by pytest conftest)",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b'{"message": "Not Found"}'),
        )

    with patch("urllib.request.urlopen", side_effect=_offline_urlopen):
        yield

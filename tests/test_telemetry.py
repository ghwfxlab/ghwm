"""Tests for ghwm.telemetry."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

from ghwm.telemetry import is_public_repository, track_installation


def _mock_http_response(body: bytes) -> MagicMock:
    mock = MagicMock()
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    mock.read.return_value = body
    return mock


class TestIsPublicRepository:
    def test_is_public_repository_should_return_true_when_api_reports_private_false(self) -> None:
        # Arrange
        response_body = json.dumps({"private": False, "name": "my-repo"}).encode()

        # Act
        with patch("ghwm.telemetry.urlopen", return_value=_mock_http_response(response_body)):
            result = is_public_repository("owner", "my-repo")

        # Assert
        assert result is True

    def test_is_public_repository_should_return_false_when_api_reports_private_true(self) -> None:
        # Arrange
        response_body = json.dumps({"private": True, "name": "my-private-repo"}).encode()

        # Act
        with patch("ghwm.telemetry.urlopen", return_value=_mock_http_response(response_body)):
            result = is_public_repository("owner", "my-private-repo")

        # Assert
        assert result is False

    def test_is_public_repository_should_return_false_when_repo_not_found(self) -> None:
        # Arrange
        not_found = HTTPError(url=None, code=404, msg="Not Found", hdrs=None, fp=None)  # type: ignore[arg-type]

        # Act
        with patch("ghwm.telemetry.urlopen", side_effect=not_found):
            result = is_public_repository("owner", "does-not-exist")

        # Assert
        assert result is False

    def test_is_public_repository_should_return_false_when_rate_limited(self) -> None:
        # Arrange
        # GitHub returns 403 with X-RateLimit-Remaining: 0 when the unauthenticated
        # limit (60 req/hour per IP) is exceeded. Telemetry must be skipped silently
        # so the install/update command still succeeds.
        rate_limited = HTTPError(url=None, code=403, msg="Forbidden", hdrs=None, fp=None)  # type: ignore[arg-type]

        # Act
        with patch("ghwm.telemetry.urlopen", side_effect=rate_limited):
            result = is_public_repository("owner", "some-repo")

        # Assert
        assert result is False

    def test_is_public_repository_should_return_false_when_unauthorized(self) -> None:
        # Arrange
        unauthorized = HTTPError(url=None, code=401, msg="Unauthorized", hdrs=None, fp=None)  # type: ignore[arg-type]

        # Act
        with patch("ghwm.telemetry.urlopen", side_effect=unauthorized):
            result = is_public_repository("owner", "some-repo")

        # Assert
        assert result is False

    def test_is_public_repository_should_return_false_on_network_error(self) -> None:
        # Arrange / Act
        with patch("ghwm.telemetry.urlopen", side_effect=URLError("Connection refused")):
            result = is_public_repository("owner", "some-repo")

        # Assert
        assert result is False

    def test_is_public_repository_should_return_false_on_malformed_json_response(self) -> None:
        # Arrange / Act
        with patch("ghwm.telemetry.urlopen", return_value=_mock_http_response(b"not-json")):
            result = is_public_repository("owner", "some-repo")

        # Assert
        assert result is False

    def test_is_public_repository_should_not_include_auth_header_in_request(self) -> None:
        # Arrange
        response_body = json.dumps({"private": False}).encode()

        # Act
        with patch("ghwm.telemetry.urlopen", return_value=_mock_http_response(response_body)):
            with patch("ghwm.telemetry.Request") as mock_request_cls:
                mock_request_cls.return_value = MagicMock()
                is_public_repository("owner", "my-repo")

        # Assert
        mock_request_cls.assert_called_once()
        _, kwargs = mock_request_cls.call_args
        assert "Authorization" not in kwargs.get("headers", {})


class TestIsPublicRepositoryIntegration:
    """Integration tests that call the real GitHub API without authentication."""

    @pytest.mark.integration
    def test_is_public_repository_should_return_true_for_known_public_repo(self) -> None:
        # Arrange / Act
        result = is_public_repository("ghwfxlab", "ghwm")

        # Assert
        assert result is True

    @pytest.mark.integration
    def test_is_public_repository_should_return_false_for_known_private_repo(self) -> None:
        # Arrange / Act
        result = is_public_repository("ghwfxlab", "ghwm-test-private")

        # Assert
        assert result is False

    @pytest.mark.integration
    def test_is_public_repository_should_return_false_for_nonexistent_repo(self) -> None:
        # Arrange / Act
        result = is_public_repository("ghwfxlab", "does-not-exist-xyz-telemetry-test")

        # Assert
        assert result is False


class TestTrackInstallation:
    def test_track_installation_should_be_a_noop_stub(self) -> None:
        # Arrange / Act / Assert: must not raise regardless of inputs
        track_installation(
            source="owner/ghwm-registry",
            workflow_name="linter",
            version="1.2.3",
            event_type="install",
        )
        track_installation(
            source="owner/ghwm-registry",
            workflow_name="linter",
            version=None,
            event_type="run",
        )

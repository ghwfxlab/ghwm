"""Tests for ghwm.telemetry."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pytest

from ghwm.telemetry import (
    PRODUCTION_TELEMETRY_URL,
    TEST_TELEMETRY_URL,
    _is_local_dev_environment,
    build_telemetry_payload,
    get_telemetry_url,
    is_public_repository,
    is_telemetry_disabled,
    track_installation,
)


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

    def test_is_public_repository_should_return_false_when_network_error_occurs(self) -> None:
        # Arrange / Act
        with patch("ghwm.telemetry.urlopen", side_effect=URLError("Connection refused")):
            result = is_public_repository("owner", "some-repo")

        # Assert
        assert result is False

    def test_is_public_repository_should_return_false_when_json_response_is_malformed(self) -> None:
        # Arrange / Act
        with patch("ghwm.telemetry.urlopen", return_value=_mock_http_response(b"not-json")):
            result = is_public_repository("owner", "some-repo")

        # Assert
        assert result is False

    def test_is_public_repository_should_return_false_and_skip_network_when_do_not_track_is_set(self) -> None:
        # Arrange / Act
        with (
            patch.dict(os.environ, {"DO_NOT_TRACK": "1"}),
            patch("ghwm.telemetry.urlopen") as mock_urlopen,
        ):
            result = is_public_repository("owner", "some-repo")

        # Assert
        assert result is False
        mock_urlopen.assert_not_called()

    def test_is_public_repository_should_return_false_and_skip_network_when_ghwm_no_telemetry_is_set(self) -> None:
        # Arrange / Act
        with (
            patch.dict(os.environ, {"GHWM_NO_TELEMETRY": "1"}),
            patch("ghwm.telemetry.urlopen") as mock_urlopen,
        ):
            result = is_public_repository("owner", "some-repo")

        # Assert
        assert result is False
        mock_urlopen.assert_not_called()

    def test_is_telemetry_disabled_should_return_true_when_env_flags_are_present(self) -> None:
        # Arrange / Act / Assert
        with patch.dict(os.environ, {"DO_NOT_TRACK": "1"}, clear=True):
            assert is_telemetry_disabled() is True

        with patch.dict(os.environ, {"GHWM_NO_TELEMETRY": "1"}, clear=True):
            assert is_telemetry_disabled() is True

        with patch.dict(os.environ, {}, clear=True):
            assert is_telemetry_disabled() is False

    def test_is_public_repository_should_omit_auth_header_when_request_is_sent(self) -> None:
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


def _is_rate_limited() -> bool:
    url = "https://api.github.com/rate_limit"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ghwm",
    }
    try:
        request = Request(url, headers=headers)  # noqa: S310
        with urlopen(request, timeout=5) as response:  # noqa: S310
            data = json.loads(response.read())
            return bool(data.get("resources", {}).get("core", {}).get("remaining", 0) == 0)
    except HTTPError as exc:
        return exc.code in {403, 429}
    except (URLError, OSError, json.JSONDecodeError, KeyError):
        return True


class TestIsPublicRepositoryIntegration:
    """Integration tests that call the real GitHub API without authentication."""

    @pytest.fixture(autouse=True)
    def check_rate_limit(self) -> None:
        if _is_rate_limited():
            pytest.skip("GitHub unauthenticated API rate limit (60 req/hr) exceeded for current IP")

    @pytest.mark.integration
    def test_is_public_repository_should_return_true_when_repository_is_public(self) -> None:
        # Arrange / Act
        result = is_public_repository("ghwfxlab", "ghwm")

        # Assert
        assert result is True

    @pytest.mark.integration
    def test_is_public_repository_should_return_false_when_repository_is_private(self) -> None:
        # Arrange / Act
        result = is_public_repository("ghwfxlab", "ghwm-test-private")

        # Assert
        assert result is False

    @pytest.mark.integration
    def test_is_public_repository_should_return_false_when_repository_does_not_exist(self) -> None:
        # Arrange / Act
        result = is_public_repository("ghwfxlab", "does-not-exist-xyz-telemetry-test")

        # Assert
        assert result is False


class TestGetTelemetryUrl:
    def test_get_telemetry_url_should_return_explicit_url_when_ghwm_telemetry_url_is_set(self) -> None:
        # Arrange
        custom_url = "https://custom.telemetry.example.com/installations"

        # Act
        with patch.dict(os.environ, {"GHWM_TELEMETRY_URL": custom_url}):
            result = get_telemetry_url()

        # Assert
        assert result == custom_url

    def test_get_telemetry_url_should_return_test_url_when_ghwm_env_is_test(self) -> None:
        # Arrange / Act
        with patch.dict(os.environ, {"GHWM_ENV": "test"}, clear=True):
            result = get_telemetry_url()

        # Assert
        assert result == TEST_TELEMETRY_URL

    def test_get_telemetry_url_should_return_test_url_when_ghwm_env_is_development(self) -> None:
        # Arrange / Act
        with patch.dict(os.environ, {"GHWM_ENV": "development"}, clear=True):
            result = get_telemetry_url()

        # Assert
        assert result == TEST_TELEMETRY_URL

    def test_get_telemetry_url_should_return_test_url_when_ci_is_set(self) -> None:
        # Arrange / Act
        with patch.dict(os.environ, {"CI": "true"}, clear=True):
            result = get_telemetry_url()

        # Assert
        assert result == TEST_TELEMETRY_URL

    def test_get_telemetry_url_should_return_test_url_when_pytest_current_test_is_set(self) -> None:
        # Arrange / Act
        with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": "test_example"}, clear=True):
            result = get_telemetry_url()

        # Assert
        assert result == TEST_TELEMETRY_URL

    def test_get_telemetry_url_should_return_test_url_when_local_dev_environment_detected(self) -> None:
        # Arrange / Act
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("ghwm.telemetry._is_local_dev_environment", return_value=True),
        ):
            result = get_telemetry_url()

        # Assert
        assert result == TEST_TELEMETRY_URL

    def test_get_telemetry_url_should_return_production_url_when_in_clean_production_environment(self) -> None:
        # Arrange / Act
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("ghwm.telemetry._is_local_dev_environment", return_value=False),
        ):
            result = get_telemetry_url()

        # Assert
        assert result == PRODUCTION_TELEMETRY_URL

    def test_is_local_dev_environment_should_return_boolean_when_evaluated(self) -> None:
        # Act
        result = _is_local_dev_environment()

        # Assert: within this repository checkout, it evaluates to True
        assert result is True

    def test_is_local_dev_environment_should_handle_os_error_when_resolving_path(self) -> None:
        # Arrange / Act
        with patch("ghwm.telemetry.Path.resolve", side_effect=OSError("Permission denied")):
            result = _is_local_dev_environment()

        # Assert
        assert result is False


class TestTrackInstallation:
    def test_track_installation_should_post_json_payload_to_resolved_telemetry_url_when_called(self) -> None:
        # Arrange
        source = "ghwfxlab/ghwm-registry"
        workflow_name = "super-linter"
        version = "1.0.1"
        event_type = "install"

        # Act
        with (
            patch("ghwm.telemetry.urlopen") as mock_urlopen,
            patch("ghwm.telemetry.Request") as mock_request_cls,
        ):
            mock_request_instance = MagicMock()
            mock_request_cls.return_value = mock_request_instance

            track_installation(
                source=source,
                workflow_name=workflow_name,
                version=version,
                event_type=event_type,
            )

        # Assert
        mock_request_cls.assert_called_once()
        args, kwargs = mock_request_cls.call_args
        called_url = args[0]
        assert called_url == get_telemetry_url()

        called_data = json.loads(kwargs["data"].decode("utf-8"))
        assert called_data["source"] == source
        assert called_data["workflow_name"] == workflow_name
        assert called_data["version"] == version
        assert called_data["event_type"] == event_type
        assert "metadata" not in called_data

        headers = kwargs["headers"]
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"
        assert "ghwm" in headers["User-Agent"]
        assert kwargs["method"] == "POST"

        mock_urlopen.assert_called_once_with(mock_request_instance, timeout=2.0)

    def test_track_installation_should_include_metadata_when_metadata_is_provided(self) -> None:
        # Arrange
        metadata = {
            "title": "Super-Linter",
            "description": "Code linting",
            "tags": ["lint", "ci"],
            "icon": "fact_check",
            "version": "1.0.1",
            "owner": "ghwfxlab",
            "source": "ghwfxlab/ghwm-registry",
        }

        # Act
        with (
            patch("ghwm.telemetry.urlopen"),
            patch("ghwm.telemetry.Request") as mock_request_cls,
        ):
            mock_request_cls.return_value = MagicMock()

            track_installation(
                source="ghwfxlab/ghwm-registry",
                workflow_name="super-linter",
                version="1.0.1",
                event_type="install",
                metadata=metadata,
            )

        # Assert
        _, kwargs = mock_request_cls.call_args
        called_data = json.loads(kwargs["data"].decode("utf-8"))
        assert called_data["metadata"] == metadata

    def test_track_installation_should_not_send_request_when_do_not_track_is_set(self) -> None:
        # Arrange / Act
        with (
            patch.dict(os.environ, {"DO_NOT_TRACK": "1"}),
            patch("ghwm.telemetry.urlopen") as mock_urlopen,
        ):
            track_installation(
                source="ghwfxlab/ghwm-registry",
                workflow_name="super-linter",
                version="1.0.1",
                event_type="install",
            )

        # Assert
        mock_urlopen.assert_not_called()

    def test_track_installation_should_not_send_request_when_ghwm_no_telemetry_is_set(self) -> None:
        # Arrange / Act
        with (
            patch.dict(os.environ, {"GHWM_NO_TELEMETRY": "1"}),
            patch("ghwm.telemetry.urlopen") as mock_urlopen,
        ):
            track_installation(
                source="ghwfxlab/ghwm-registry",
                workflow_name="super-linter",
                version="1.0.1",
                event_type="install",
            )

        # Assert
        mock_urlopen.assert_not_called()

    def test_track_installation_should_silently_suppress_http_error_when_server_fails(self) -> None:
        # Arrange
        server_error = HTTPError(url=None, code=500, msg="Server Error", hdrs=None, fp=None)  # type: ignore[arg-type]

        # Act / Assert: Must not propagate exception
        with patch("ghwm.telemetry.urlopen", side_effect=server_error):
            track_installation(
                source="ghwfxlab/ghwm-registry",
                workflow_name="super-linter",
                version="1.0.1",
                event_type="install",
            )

    def test_track_installation_should_silently_suppress_url_error_when_network_fails(self) -> None:
        # Arrange
        network_error = URLError("Network unreachable")

        # Act / Assert: Must not propagate exception
        with patch("ghwm.telemetry.urlopen", side_effect=network_error):
            track_installation(
                source="ghwfxlab/ghwm-registry",
                workflow_name="super-linter",
                version="1.0.1",
                event_type="install",
            )

    def test_track_installation_should_silently_suppress_timeout_error_when_request_times_out(self) -> None:
        # Arrange
        timeout_error = TimeoutError("Connection timed out")

        # Act / Assert: Must not propagate exception
        with patch("ghwm.telemetry.urlopen", side_effect=timeout_error):
            track_installation(
                source="ghwfxlab/ghwm-registry",
                workflow_name="super-linter",
                version="1.0.1",
                event_type="install",
            )

    def test_track_installation_should_silently_suppress_os_error_when_io_fails(self) -> None:
        # Arrange
        os_error = OSError("Socket error")

        # Act / Assert: Must not propagate exception
        with patch("ghwm.telemetry.urlopen", side_effect=os_error):
            track_installation(
                source="ghwfxlab/ghwm-registry",
                workflow_name="super-linter",
                version="1.0.1",
                event_type="install",
            )


@pytest.mark.integration
class TestPrivateRepositoryIsolationLive:
    """Live verification against the test telemetry endpoint for private repository isolation."""

    def test_private_repository_should_never_post_telemetry_to_test_endpoint_when_evaluated(
        self,
    ) -> None:
        # Arrange: Query test telemetry stats endpoint for baseline count of private repository
        private_source = "ghwfxlab/ghwm-test-private"
        stats_url = f"https://ghwm-deployment-tst.ghwfxlab.workers.dev/stats?source={private_source}"
        stats_req = Request(stats_url, headers={"User-Agent": "ghwm"})  # noqa: S310
        with urlopen(stats_req, timeout=5) as response:  # noqa: S310
            stats_before = json.loads(response.read().decode())
        baseline_count = stats_before.get("total_installations", 0)

        # Act: Evaluate workflow installation from private repository source
        from ghwm.install import InstallResult, _emit_telemetry
        from ghwm.manifest import Manifest, WorkflowEntry

        manifest = Manifest(
            source=private_source,
            workflows=[WorkflowEntry(name="private-workflow", version="1.0.0", source=private_source)],
        )
        install_result = InstallResult(installed=["private-workflow"], updated=[], pruned=[], skipped=[])
        _emit_telemetry(private_source, manifest, install_result)

        # Assert: Query test telemetry stats endpoint again; count must not increase and must remain 0
        stats_req_after = Request(stats_url, headers={"User-Agent": "ghwm"})  # noqa: S310
        with urlopen(stats_req_after, timeout=5) as response_after:  # noqa: S310
            stats_after = json.loads(response_after.read().decode())
        final_count = stats_after.get("total_installations", 0)

        assert final_count == baseline_count == 0
        assert stats_after.get("workflows") == []


class TestBuildTelemetryPayload:
    def test_build_telemetry_payload_should_include_metadata_when_metadata_is_provided(self) -> None:
        # Arrange
        metadata = {"title": "Linter", "version": "1.0.0"}

        # Act
        payload = build_telemetry_payload(workflow_name="linter", action="install", metadata=metadata)

        # Assert
        assert payload == {
            "workflow_name": "linter",
            "action": "install",
            "metadata": {"title": "Linter", "version": "1.0.0"},
        }

    def test_build_telemetry_payload_should_omit_metadata_when_metadata_is_none(self) -> None:
        # Arrange / Act
        payload = build_telemetry_payload(workflow_name="linter", action="updated", metadata=None)

        # Assert
        assert payload == {
            "workflow_name": "linter",
            "action": "updated",
        }

"""Tests for ghwm.download."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest

from ghwm.download import WorkflowSource, download_workflows, gh_cli_available, github_token, read_from_tree
from ghwm.download_npm import InstalledFile


class TestGithubToken:
    def test_github_token_should_prefer_environment_variable_over_gh_cli_token_when_gh_cli_also_returns_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GH_TOKEN", "env-token")

        with (
            patch("ghwm.download.gh_cli_available", return_value=True),
            patch("ghwm.download.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="gh-token\n")
            token = github_token()

        assert token == "env-token"

    def test_github_token_should_read_gh_auth_token_when_gh_cli_is_available(self) -> None:
        with (
            patch("ghwm.download.gh_cli_available", return_value=True),
            patch("ghwm.download.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="gh-token\n")
            token = github_token()

        assert token == "gh-token"

    def test_github_token_should_fall_back_to_environment_variables_when_gh_cli_lookup_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GH_TOKEN", "env-token")

        with (
            patch("ghwm.download.gh_cli_available", return_value=True),
            patch("ghwm.download.subprocess.run", return_value=MagicMock(returncode=1, stdout="")),
        ):
            token = github_token()

        assert token == "env-token"

    def test_github_token_should_propagate_unexpected_process_execution_errors_when_gh_cli_lookup_raises_os_error(
        self,
    ) -> None:
        with (
            patch("ghwm.download.gh_cli_available", return_value=True),
            patch("ghwm.download.subprocess.run", side_effect=OSError("boom")),
        ):
            with pytest.raises(OSError, match="boom"):
                github_token()

    def test_github_token_should_return_none_when_no_auth_source_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

        with patch("ghwm.download.gh_cli_available", return_value=False):
            token = github_token()

        assert token is None


class TestGhCliAvailable:
    def test_gh_cli_available_should_return_bool_when_checked(self) -> None:
        assert isinstance(gh_cli_available(), bool)


class TestReadFromTree:
    def _setup_marketplace(self, root: Path, name: str = "auto-assign-pr") -> None:
        workflow_dir = root / "workflows" / name
        (workflow_dir / "config").mkdir(parents=True)
        (workflow_dir / "workflow.yml").write_text(
            "name: auto-assign-pr\n"
            "files:\n"
            "  - source: auto-assign-pr.yaml\n"
            "    target: .github/workflows/auto-assign-pr.yaml\n"
            "  - source: config/auto_assign.yaml\n"
            "    target: .github/auto_assign.yaml\n"
        )
        (workflow_dir / "auto-assign-pr.yaml").write_text("name: auto-assign-pr\n")
        (workflow_dir / "config" / "auto_assign.yaml").write_text("addReviewers: false\n")

    def test_read_from_tree_should_return_workflow_source_with_all_packaged_files_when_workflow_package_is_complete(
        self, tmp_path: Path
    ) -> None:
        self._setup_marketplace(tmp_path)

        results = read_from_tree(tmp_path, "owner/ghwm-marketplace", ["auto-assign-pr"])

        assert len(results) == 1
        assert results[0].name == "auto-assign-pr"
        assert results[0].package_name == "@owner/ghwm-auto-assign-pr"
        assert len(results[0].files) == 2
        assert results[0].files[0].content == b"name: auto-assign-pr\n"
        assert results[0].files[0].target == ".github/workflows/auto-assign-pr.yaml"

    def test_read_from_tree_should_raise_when_workflow_manifest_is_missing(self, tmp_path: Path) -> None:
        workflow_dir = tmp_path / "workflows" / "linter"
        workflow_dir.mkdir(parents=True)

        with pytest.raises(FileNotFoundError) as exc_info:
            read_from_tree(tmp_path, "owner/ghwm-marketplace", ["linter"])

        assert "workflow.yml" in str(exc_info.value)


class TestDownloadWorkflowsLocal:
    def test_download_workflows_should_read_single_workflow_when_local_path_is_provided(self, tmp_path: Path) -> None:
        workflow_dir = tmp_path / "marketplace" / "workflows" / "linter"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "workflow.yml").write_text(
            "name: linter\nfiles:\n  - source: linter.yml\n    target: .github/workflows/linter.yml\n"
        )
        (workflow_dir / "linter.yml").write_text("name: linter\n")

        results = download_workflows(
            "owner/ghwm-marketplace",
            ["linter"],
            {"linter": "1.0.0"},
            local_path=tmp_path / "marketplace",
        )

        assert len(results) == 1
        assert isinstance(results[0], WorkflowSource)
        assert results[0].files[0].content == b"name: linter\n"


class TestDownloadWorkflowsRemote:
    def test_download_workflows_should_download_package_from_github_packages_when_remote_version_is_provided(
        self,
    ) -> None:
        installed_files = [
            InstalledFile(
                source="linter.yml",
                content=b"name: linter\n",
                target=".github/workflows/linter.yml",
            )
        ]

        with (
            patch("ghwm.download.github_token", return_value="token"),
            patch("ghwm.download.download_npm_tarball", return_value=Path("/tmp/package.tgz")) as mock_download,
            patch("ghwm.download.read_workflow_manifest", return_value={"files": []}),
            patch("ghwm.download.extract_npm_package", return_value=installed_files),
        ):
            results = download_workflows(
                "owner/ghwm-marketplace",
                ["linter"],
                {"linter": "1.0.0"},
            )

        assert results[0].package_name == "@owner/ghwm-linter"
        mock_download.assert_called_once_with("owner", "linter", "1.0.0", ANY, "token")

    def test_download_workflows_should_raise_when_version_is_missing_for_remote_download(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            download_workflows("owner/ghwm-marketplace", ["linter"], {})

        assert "must specify a version" in str(exc_info.value)

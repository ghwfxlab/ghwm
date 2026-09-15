"""Tests for ghwm.download."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest

from ghwm.download import WorkflowSource, download_workflows, gh_cli_available, github_token, read_from_tree
from ghwm.download_npm import InstalledFile
from ghwm.manifest import Manifest, WorkflowEntry
from tests.shared import (
    AUTO_ASSIGN_PR,
    AUTO_ASSIGN_PR_PACKAGE_SOURCE,
    LINTER,
    LINTER_PACKAGE_SOURCE,
    MARKETPLACE_SOURCE,
    VERSION_1,
)


class TestGithubToken:
    def test_github_token_should_prefer_environment_variable_over_gh_cli_token_when_gh_cli_also_returns_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Arrange
        monkeypatch.setenv("GH_TOKEN", "env-token")

        # Act
        with (
            patch("ghwm.download.gh_cli_available", return_value=True),
            patch("ghwm.download.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="gh-token\n")
            token = github_token()

        # Assert
        assert token == "env-token"

    def test_github_token_should_read_gh_auth_token_when_gh_cli_is_available(self) -> None:
        # Arrange / Act
        with (
            patch("ghwm.download.gh_cli_available", return_value=True),
            patch("ghwm.download.subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0, stdout="gh-token\n")
            token = github_token()

        # Assert
        assert token == "gh-token"

    def test_github_token_should_fall_back_to_environment_variables_when_gh_cli_lookup_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Arrange
        monkeypatch.setenv("GH_TOKEN", "env-token")

        # Act
        with (
            patch("ghwm.download.gh_cli_available", return_value=True),
            patch("ghwm.download.subprocess.run", return_value=MagicMock(returncode=1, stdout="")),
        ):
            token = github_token()

        # Assert
        assert token == "env-token"

    def test_github_token_should_propagate_unexpected_process_execution_errors_when_gh_cli_lookup_raises_os_error(
        self,
    ) -> None:
        # Arrange / Act & Assert
        with (
            patch("ghwm.download.gh_cli_available", return_value=True),
            patch("ghwm.download.subprocess.run", side_effect=OSError("boom")),
        ):
            with pytest.raises(OSError, match="boom"):
                github_token()

    def test_github_token_should_return_none_when_no_auth_source_exists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Arrange
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

        # Act
        with patch("ghwm.download.gh_cli_available", return_value=False):
            token = github_token()

        # Assert
        assert token is None


class TestGhCliAvailable:
    def test_gh_cli_available_should_return_bool_when_checked(self) -> None:
        # Act / Assert
        assert isinstance(gh_cli_available(), bool)


class TestReadFromTree:
    def _setup_marketplace(self, root: Path, name: str = AUTO_ASSIGN_PR) -> None:
        workflow_dir = root / "workflows" / name
        (workflow_dir / "config").mkdir(parents=True)
        (workflow_dir / "workflow.yml").write_text(
            f"name: {AUTO_ASSIGN_PR}\n"
            "files:\n"
            f"  - source: {AUTO_ASSIGN_PR}.yaml\n"
            f"    target: .github/workflows/{AUTO_ASSIGN_PR}.yaml\n"
            f"  - source: config/auto_assign.yaml\n"
            f"    target: .github/auto_assign.yaml\n"
        )
        (workflow_dir / f"{AUTO_ASSIGN_PR}.yaml").write_text(f"name: {AUTO_ASSIGN_PR}\n")
        (workflow_dir / "config" / "auto_assign.yaml").write_text("addReviewers: false\n")

    def test_read_from_tree_should_return_workflow_source_with_all_packaged_files_when_workflow_package_is_complete(
        self, tmp_path: Path
    ) -> None:
        # Arrange
        self._setup_marketplace(tmp_path)

        # Act
        results = read_from_tree(
            tmp_path, Manifest(source=MARKETPLACE_SOURCE, workflows=[WorkflowEntry(name=AUTO_ASSIGN_PR)])
        )

        # Assert
        assert len(results) == 1
        assert results[0].name == AUTO_ASSIGN_PR
        assert results[0].package_name == AUTO_ASSIGN_PR_PACKAGE_SOURCE
        assert len(results[0].files) == 2
        assert results[0].files[0].content == f"name: {AUTO_ASSIGN_PR}\n".encode()
        assert results[0].files[0].target == f".github/workflows/{AUTO_ASSIGN_PR}.yaml"

    def test_read_from_tree_should_extract_metadata_when_package_contains_frontmatter(self, tmp_path: Path) -> None:
        # Arrange
        workflow_dir = tmp_path / "workflows" / LINTER
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "workflow.yml").write_text(
            "# ---\n"
            "# title: Linter CI\n"
            "# description: Fast linting\n"
            "# tags:\n"
            "#   - lint\n"
            "# icon: task\n"
            "# ---\n"
            "name: linter\n"
            "files:\n"
            "  - source: linter.yaml\n"
            "    target: .github/workflows/linter.yaml\n"
        )
        (workflow_dir / "linter.yaml").write_text("name: linter\n")
        (workflow_dir / "package.json").write_text('{"version": "1.2.0"}')

        # Act
        results = read_from_tree(tmp_path, Manifest(source=MARKETPLACE_SOURCE, workflows=[WorkflowEntry(name=LINTER)]))

        # Assert
        assert results[0].metadata is not None
        assert results[0].metadata["title"] == "Linter CI"
        assert results[0].metadata["description"] == "Fast linting"
        assert results[0].metadata["tags"] == ["lint"]
        assert results[0].metadata["icon"] == "task"
        assert results[0].metadata["version"] == "1.2.0"

    def test_read_from_tree_should_extract_metadata_from_workflow_file_in_files_when_name_yaml_is_absent(
        self, tmp_path: Path
    ) -> None:
        # Arrange
        workflow_dir = tmp_path / "workflows" / "myflow"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "workflow.yml").write_text(
            "name: myflow\n"
            "files:\n"
            "  - source: config.json\n"
            "    target: config.json\n"
            "  - source: actions.yaml\n"
            "    target: .github/workflows/actions.yaml\n"
        )
        (workflow_dir / "config.json").write_text("{}")
        (workflow_dir / "actions.yaml").write_text("# ---\n# title: Action Flow\n# ---\nname: actions\n")

        # Act
        results = read_from_tree(
            tmp_path, Manifest(source=MARKETPLACE_SOURCE, workflows=[WorkflowEntry(name="myflow")])
        )

        # Assert
        assert results[0].metadata is not None
        assert results[0].metadata["title"] == "Action Flow"

    def test_read_from_tree_should_return_metadata_without_title_when_package_has_no_workflow_files(
        self, tmp_path: Path
    ) -> None:
        # Arrange
        workflow_dir = tmp_path / "workflows" / "onlyconfig"
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "workflow.yml").write_text(
            "name: onlyconfig\nfiles:\n  - source: config.json\n    target: config.json\n"
        )
        (workflow_dir / "config.json").write_text("{}")

        # Act
        results = read_from_tree(
            tmp_path, Manifest(source=MARKETPLACE_SOURCE, workflows=[WorkflowEntry(name="onlyconfig")])
        )

        # Assert
        assert results[0].metadata is not None
        assert results[0].metadata["title"] is None

    def test_read_from_tree_should_raise_file_not_found_when_workflow_manifest_is_missing(self, tmp_path: Path) -> None:
        # Arrange
        workflow_dir = tmp_path / "workflows" / LINTER
        workflow_dir.mkdir(parents=True)

        # Act & Assert
        with pytest.raises(FileNotFoundError) as exc_info:
            read_from_tree(tmp_path, Manifest(source=MARKETPLACE_SOURCE, workflows=[WorkflowEntry(name=LINTER)]))

        assert "workflow.yml" in str(exc_info.value)


class TestDownloadWorkflowsLocal:
    def test_download_workflows_should_read_single_workflow_when_local_path_is_provided(self, tmp_path: Path) -> None:
        # Arrange
        workflow_dir = tmp_path / "marketplace" / "workflows" / LINTER
        workflow_dir.mkdir(parents=True)
        (workflow_dir / "workflow.yml").write_text(
            "name: linter\nfiles:\n  - source: linter.yml\n    target: .github/workflows/linter.yml\n"
        )
        (workflow_dir / f"{LINTER}.yml").write_text(f"name: {LINTER}\n")

        # Act
        results = download_workflows(
            Manifest(source=MARKETPLACE_SOURCE, workflows=[WorkflowEntry(name=LINTER, version=VERSION_1)]),
            local_path=tmp_path / "marketplace",
        )

        # Assert
        assert len(results) == 1
        assert isinstance(results[0], WorkflowSource)
        assert results[0].files[0].content == b"name: linter\n"


class TestDownloadWorkflowsRemote:
    def test_download_workflows_should_download_package_from_github_packages_when_remote_version_is_provided(
        self,
    ) -> None:
        # Arrange
        installed_files = [
            InstalledFile(
                source=f"{LINTER}.yml",
                content=f"name: {LINTER}\n".encode(),
                target=f".github/workflows/{LINTER}.yml",
            )
        ]

        # Act
        with (
            patch("ghwm.download.github_token", return_value="token"),
            patch("ghwm.download.download_npm_tarball", return_value=Path("/tmp/package.tgz")) as mock_download,
            patch("ghwm.download.read_workflow_manifest", return_value={"files": []}),
            patch("ghwm.download.extract_npm_package", return_value=installed_files),
        ):
            results = download_workflows(
                Manifest(source=MARKETPLACE_SOURCE, workflows=[WorkflowEntry(name=LINTER, version=VERSION_1)])
            )

        # Assert
        assert results[0].package_name == LINTER_PACKAGE_SOURCE
        assert results[0].metadata is not None
        assert results[0].metadata["source"] == MARKETPLACE_SOURCE
        assert results[0].metadata["version"] == VERSION_1
        mock_download.assert_called_once_with("owner", LINTER, VERSION_1, ANY, "token")

    def test_download_workflows_should_raise_file_not_found_when_package_version_is_missing(
        self,
    ) -> None:
        # Arrange / Act & Assert
        # Since it defaults to latest, it will attempt to download from the registry.
        # We expect a FileNotFoundError because the dummy package @owner/linter doesn't exist.
        with pytest.raises(FileNotFoundError):
            download_workflows(Manifest(source=MARKETPLACE_SOURCE, workflows=[WorkflowEntry(name=LINTER)]))

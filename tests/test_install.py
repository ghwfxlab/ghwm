"""Tests for ghwm.install."""

from __future__ import annotations

from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

from ghwm.install import install_workflows, update_workflows
from ghwm.lock import read_lockfile
from ghwm.managed_files import _extract_body, _load_workflow_yaml
from ghwm.manifest import Manifest, parse_manifest
from tests.shared import (
    AUTO_ASSIGN_PR,
    LINTER,
    LINTER_PACKAGE_SOURCE,
    MARKETPLACE_SOURCE,
    VERSION_1,
    VERSION_1_2_3,
    WORKFLOWS_DIR,
)


def _marketplace_manifest(workflows: list[dict[str, object]]) -> Manifest:
    return parse_manifest({"source": MARKETPLACE_SOURCE, "workflows": workflows})


def _workflow_path(consumer: Path, name: str) -> Path:
    return consumer / WORKFLOWS_DIR / f"{name}.yaml"


def _write_marketplace_package(
    marketplace: Path,
    name: str,
    workflow_content: str,
    *,
    config_content: str | None = None,
) -> None:
    workflow_dir = marketplace / "workflows" / name
    workflow_dir.mkdir(parents=True, exist_ok=True)

    manifest_lines = [
        f"name: {name}",
        "files:",
        f"  - source: {name}.yaml",
        f"    target: .github/workflows/{name}.yaml",
    ]
    (workflow_dir / f"{name}.yaml").write_text(workflow_content)

    if config_content is not None:
        (workflow_dir / "config").mkdir(exist_ok=True)
        (workflow_dir / "config" / "config.yml").write_text(config_content)
        manifest_lines.extend(
            [
                "  - source: config/config.yml",
                "    target: .github/config.yml",
            ]
        )

    (workflow_dir / "workflow.yml").write_text("\n".join(manifest_lines) + "\n")


class TestInstallWorkflows:
    def test_install_workflows_should_use_custom_target_for_workflow_file_when_manifest_entry_defines_target(
        self, tmp_path: Path
    ) -> None:
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(marketplace, LINTER, "name: linter\non: push\n")
        manifest = _marketplace_manifest([{"name": LINTER, "version": VERSION_1_2_3, "target": "custom-review.yml"}])

        install_workflows(consumer, manifest, local_path=marketplace)

        assert (consumer / ".github" / "workflows" / "custom-review.yml").is_file()

    def test_install_workflows_should_install_workflow_and_record_lockfile_when_local_package_is_available(
        self, tmp_path: Path
    ) -> None:
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(marketplace, LINTER, "name: linter\non: push\n")
        manifest = _marketplace_manifest([{"name": LINTER, "version": VERSION_1_2_3}])

        result = install_workflows(consumer, manifest, local_path=marketplace)

        installed_path = _workflow_path(consumer, LINTER)
        lockfile = read_lockfile(consumer)

        assert result.installed == [LINTER]
        assert installed_path.is_file()
        assert f"# Managed by ghwm ({LINTER}@{VERSION_1_2_3})" in installed_path.read_text()
        assert lockfile.packages[0].source == LINTER_PACKAGE_SOURCE
        assert lockfile.packages[0].files[0].target == f".github/workflows/{LINTER}.yaml"

    def test_install_workflows_should_skip_unmanaged_existing_workflow_file_when_target_workflow_file_exists(
        self, tmp_path: Path
    ) -> None:
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(marketplace, LINTER, "name: linter\non: push\n")
        workflow_path = _workflow_path(consumer, LINTER)
        workflow_path.parent.mkdir(parents=True)
        workflow_path.write_text("name: custom\n")
        manifest = _marketplace_manifest([{"name": LINTER, "version": VERSION_1_2_3}])

        result = install_workflows(consumer, manifest, local_path=marketplace)
        lockfile = read_lockfile(consumer)

        assert result.skipped == [(LINTER, "unmanaged file exists")]
        assert workflow_path.read_text() == "name: custom\n"
        assert lockfile.packages == []

    def test_install_workflows_should_seed_config_file_on_first_install_when_packaged_config_file_is_missing(
        self, tmp_path: Path
    ) -> None:
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(
            marketplace,
            AUTO_ASSIGN_PR,
            "name: auto-assign-pr\non: pull_request\n",
            config_content="enabled: true\n",
        )
        manifest = _marketplace_manifest([{"name": AUTO_ASSIGN_PR, "version": VERSION_1}])

        install_workflows(consumer, manifest, local_path=marketplace)

        assert (consumer / ".github" / "config.yml").read_text() == "enabled: true\n"

    def test_install_workflows_should_leave_existing_config_file_untouched_on_first_install_when_config_file_exists(
        self, tmp_path: Path
    ) -> None:
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        (consumer / ".github").mkdir()
        (consumer / ".github" / "config.yml").write_text("custom: true\n")
        _write_marketplace_package(
            marketplace,
            AUTO_ASSIGN_PR,
            "name: auto-assign-pr\non: pull_request\n",
            config_content="enabled: true\n",
        )
        manifest = _marketplace_manifest([{"name": AUTO_ASSIGN_PR, "version": VERSION_1}])

        install_workflows(consumer, manifest, local_path=marketplace)
        lockfile = read_lockfile(consumer)

        assert (consumer / ".github" / "config.yml").read_text() == "custom: true\n"
        assert [file_entry.target for file_entry in lockfile.packages[0].files] == [
            f".github/workflows/{AUTO_ASSIGN_PR}.yaml"
        ]

    def test_update_workflows_should_preserve_existing_triggers_by_default_when_installed_workflow_has_custom_triggers(
        self, tmp_path: Path
    ) -> None:
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(
            marketplace,
            "linter",
            "name: v1\non:\n  push:\n    branches:\n      - main\njobs:\n  review:\n    runs-on: ubuntu-latest\n",
        )
        manifest = _marketplace_manifest([{"name": LINTER, "version": VERSION_1}])
        install_workflows(consumer, manifest, local_path=marketplace)

        installed_path = _workflow_path(consumer, LINTER)
        installed_path.write_text(
            installed_path.read_text().replace("- main", "- release/*"),
            encoding="utf-8",
        )
        _write_marketplace_package(
            marketplace,
            "linter",
            "name: v2\non:\n  pull_request:\njobs:\n  review:\n    runs-on: ubuntu-latest\n",
        )

        update_workflows(consumer, manifest, local_path=marketplace)

        body = cast(dict[str, object], _load_workflow_yaml(_extract_body(installed_path.read_text())))
        assert body["name"] == "v2"
        assert body["on"] == {"push": {"branches": ["release/*"]}}

    def test_install_workflows_should_prune_updated_workflow_after_trigger_merge_when_workflow_becomes_stale(
        self, tmp_path: Path
    ) -> None:
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(
            marketplace,
            "linter",
            "name: v1\non:\n  push:\n    branches:\n      - main\njobs:\n  review:\n    runs-on: ubuntu-latest\n",
        )
        manifest = _marketplace_manifest([{"name": LINTER, "version": VERSION_1}])
        empty_manifest = _marketplace_manifest([])
        install_workflows(consumer, manifest, local_path=marketplace)
        _write_marketplace_package(
            marketplace,
            "linter",
            "name: v2\non:\n  pull_request:\njobs:\n  review:\n    runs-on: ubuntu-latest\n",
        )

        update_workflows(consumer, manifest, local_path=marketplace)
        result = install_workflows(consumer, empty_manifest, local_path=marketplace)

        assert result.pruned == [LINTER]
        assert not _workflow_path(consumer, LINTER).exists()

    def test_update_workflows_should_raise_when_existing_workflow_yaml_is_not_a_mapping(self, tmp_path: Path) -> None:
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(marketplace, LINTER, "name: v1\non: push\n")
        manifest = _marketplace_manifest([{"name": LINTER, "version": VERSION_1}])
        install_workflows(consumer, manifest, local_path=marketplace)
        installed_path = _workflow_path(consumer, LINTER)
        installed_path.write_text(
            f"# Managed by ghwm ({LINTER}@{VERSION_1})\n"
            "# Source: anything\n"
            "# Hash: sha256:anything\n"
            "# Re-run `ghwm install` to refresh this file.\n\n"
            "- not\n- a\n- mapping\n",
            encoding="utf-8",
        )
        _write_marketplace_package(marketplace, LINTER, "name: v2\non: pull_request\n")

        with pytest.raises(ValueError, match="mapping"):
            update_workflows(consumer, manifest, local_path=marketplace)

    def test_update_workflows_should_keep_new_triggers_when_existing_workflow_has_no_on_section(
        self, tmp_path: Path
    ) -> None:
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(marketplace, LINTER, "name: v1\njobs:\n  review:\n    runs-on: ubuntu-latest\n")
        manifest = parse_manifest(
            {
                "source": "owner/ghwm-registry",
                "workflows": [{"name": LINTER, "version": VERSION_1}],
            }
        )
        install_workflows(consumer, manifest, local_path=marketplace)
        _write_marketplace_package(marketplace, LINTER, "name: v2\non: pull_request\n")

        update_workflows(consumer, manifest, local_path=marketplace)

        installed_path = consumer / ".github" / "workflows" / "linter.yaml"
        body = cast(
            dict[str, object],
            _load_workflow_yaml(_extract_body(installed_path.read_text())),
        )
        assert body["on"] == "pull_request"

    def test_update_workflows_should_replace_triggers_when_manifest_requests_it(self, tmp_path: Path) -> None:
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(
            marketplace,
            "linter",
            "name: v1\non:\n  push:\n    branches:\n      - main\n",
        )
        manifest = parse_manifest(
            {
                "source": "owner/ghwm-registry",
                "workflows": [{"name": LINTER, "version": VERSION_1, "update-triggers": True}],
            }
        )
        install_workflows(consumer, manifest, local_path=marketplace)

        installed_path = consumer / ".github" / "workflows" / "linter.yaml"
        installed_path.write_text(
            installed_path.read_text().replace("- main", "- release/*"),
            encoding="utf-8",
        )
        _write_marketplace_package(marketplace, LINTER, "name: v2\non:\n  pull_request:\n")

        update_workflows(consumer, manifest, local_path=marketplace)

        body = cast(dict[str, object], _load_workflow_yaml(_extract_body(installed_path.read_text())))
        assert body["name"] == "v2"
        assert body["on"] == {"pull_request": None}

    def test_update_workflows_should_replace_triggers_when_run_requests_global_override(self, tmp_path: Path) -> None:
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(
            marketplace,
            "linter",
            "name: v1\non:\n  push:\n    branches:\n      - main\n",
        )
        manifest = parse_manifest(
            {
                "source": "owner/ghwm-registry",
                "workflows": [{"name": LINTER, "version": VERSION_1}],
            }
        )
        install_workflows(consumer, manifest, local_path=marketplace)

        installed_path = consumer / ".github" / "workflows" / "linter.yaml"
        installed_path.write_text(
            installed_path.read_text().replace("- main", "- release/*"),
            encoding="utf-8",
        )
        _write_marketplace_package(marketplace, LINTER, "name: v2\non:\n  pull_request:\n")

        update_workflows(consumer, manifest, local_path=marketplace, update_triggers=True)

        body = cast(dict[str, object], _load_workflow_yaml(_extract_body(installed_path.read_text())))
        assert body["on"] == {"pull_request": None}

    def test_update_workflows_should_leave_config_file_untouched_when_update_config_files_is_false(
        self, tmp_path: Path
    ) -> None:
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(
            marketplace,
            AUTO_ASSIGN_PR,
            "name: v1\non: pull_request\n",
            config_content="enabled: true\n",
        )
        manifest = parse_manifest(
            {
                "source": "owner/ghwm-registry",
                "workflows": [{"name": AUTO_ASSIGN_PR, "version": VERSION_1}],
            }
        )
        install_workflows(consumer, manifest, local_path=marketplace)
        (consumer / ".github" / "config.yml").write_text("custom: true\n")
        _write_marketplace_package(
            marketplace,
            AUTO_ASSIGN_PR,
            "name: v2\non: pull_request\n",
            config_content="enabled: false\n",
        )

        update_workflows(consumer, manifest, local_path=marketplace)

        assert (consumer / ".github" / "config.yml").read_text() == "custom: true\n"

    def test_update_workflows_should_not_create_new_config_file_when_updates_are_disabled(self, tmp_path: Path) -> None:
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(marketplace, AUTO_ASSIGN_PR, "name: v1\non: pull_request\n")
        manifest = parse_manifest(
            {
                "source": "owner/ghwm-registry",
                "workflows": [{"name": AUTO_ASSIGN_PR, "version": VERSION_1}],
            }
        )
        install_workflows(consumer, manifest, local_path=marketplace)
        _write_marketplace_package(
            marketplace,
            AUTO_ASSIGN_PR,
            "name: v2\non: pull_request\n",
            config_content="enabled: true\n",
        )

        update_workflows(consumer, manifest, local_path=marketplace)
        lockfile = read_lockfile(consumer)

        assert not (consumer / ".github" / "config.yml").exists()
        assert lockfile.packages[0].find_file(".github/config.yml") is None

    def test_update_workflows_should_replace_config_file_when_update_config_files_is_true(self, tmp_path: Path) -> None:
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(
            marketplace,
            AUTO_ASSIGN_PR,
            "name: v1\non: pull_request\n",
            config_content="enabled: true\n",
        )
        install_manifest = parse_manifest(
            {
                "source": "owner/ghwm-registry",
                "workflows": [{"name": AUTO_ASSIGN_PR, "version": VERSION_1}],
            }
        )
        update_manifest = parse_manifest(
            {
                "source": "owner/ghwm-registry",
                "workflows": [
                    {
                        "name": "auto-assign-pr",
                        "version": "1.0.0",
                        "update-config-files": True,
                    }
                ],
            }
        )
        install_workflows(consumer, install_manifest, local_path=marketplace)
        (consumer / ".github" / "config.yml").write_text("custom: true\n")
        _write_marketplace_package(
            marketplace,
            AUTO_ASSIGN_PR,
            "name: v2\non: pull_request\n",
            config_content="enabled: false\n",
        )

        update_workflows(consumer, update_manifest, local_path=marketplace)
        lockfile = read_lockfile(consumer)

        assert (consumer / ".github" / "config.yml").read_text() == "enabled: false\n"
        config_entry = lockfile.packages[0].find_file(".github/config.yml")
        assert config_entry is not None
        assert config_entry.overwrite is True

    def test_update_workflows_should_leave_stale_workflow_when_prune_is_not_requested(self, tmp_path: Path) -> None:
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(marketplace, LINTER, "name: linter\non: push\n")
        install_manifest = parse_manifest(
            {
                "source": "owner/ghwm-registry",
                "workflows": [{"name": LINTER, "version": VERSION_1}],
            }
        )
        empty_manifest = parse_manifest({"source": MARKETPLACE_SOURCE, "workflows": []})
        install_workflows(consumer, install_manifest, local_path=marketplace)

        result = update_workflows(consumer, empty_manifest, local_path=marketplace)
        lockfile = read_lockfile(consumer)

        assert result.pruned == []
        assert (consumer / ".github" / "workflows" / "linter.yaml").exists()
        assert lockfile.find("linter") is not None

    def test_update_workflows_should_prune_stale_workflow_when_prune_is_requested(self, tmp_path: Path) -> None:
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(marketplace, LINTER, "name: linter\non: push\n")
        install_manifest = parse_manifest(
            {
                "source": "owner/ghwm-registry",
                "workflows": [{"name": LINTER, "version": VERSION_1}],
            }
        )
        empty_manifest = parse_manifest({"source": MARKETPLACE_SOURCE, "workflows": []})
        install_workflows(consumer, install_manifest, local_path=marketplace)

        result = update_workflows(consumer, empty_manifest, local_path=marketplace, prune=True)
        lockfile = read_lockfile(consumer)

        assert result.pruned == [LINTER]
        assert not (consumer / ".github" / "workflows" / "linter.yaml").exists()
        assert lockfile.find("linter") is None

    def test_update_workflows_should_prune_stale_workflow_but_keep_config_files_when_prune_is_requested(
        self, tmp_path: Path
    ) -> None:
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(
            marketplace,
            AUTO_ASSIGN_PR,
            "name: auto-assign-pr\non: pull_request\n",
            config_content="enabled: true\n",
        )
        manifest = parse_manifest(
            {
                "source": "owner/ghwm-registry",
                "workflows": [{"name": AUTO_ASSIGN_PR, "version": VERSION_1}],
            }
        )
        empty_manifest = parse_manifest({"source": MARKETPLACE_SOURCE, "workflows": []})
        install_workflows(consumer, manifest, local_path=marketplace)

        result = update_workflows(consumer, empty_manifest, local_path=marketplace, prune=True)

        assert result.pruned == [AUTO_ASSIGN_PR]
        assert not (consumer / ".github" / "workflows" / "auto-assign-pr.yaml").exists()
        assert (consumer / ".github" / "config.yml").read_text() == "enabled: true\n"

    def test_install_workflows_should_prune_workflow_but_keep_config_files_when_package_is_stale(
        self, tmp_path: Path
    ) -> None:
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(
            marketplace,
            AUTO_ASSIGN_PR,
            "name: auto-assign-pr\non: pull_request\n",
            config_content="enabled: true\n",
        )
        manifest = parse_manifest(
            {
                "source": "owner/ghwm-registry",
                "workflows": [{"name": AUTO_ASSIGN_PR, "version": VERSION_1}],
            }
        )
        empty_manifest = parse_manifest({"source": MARKETPLACE_SOURCE, "workflows": []})
        install_workflows(consumer, manifest, local_path=marketplace)

        result = install_workflows(consumer, empty_manifest, local_path=marketplace)

        assert result.pruned == [AUTO_ASSIGN_PR]
        assert not (consumer / ".github" / "workflows" / "auto-assign-pr.yaml").exists()
        assert (consumer / ".github" / "config.yml").read_text() == "enabled: true\n"

    def test_install_workflows_should_skip_pruning_when_stale_workflow_file_is_unmanaged(self, tmp_path: Path) -> None:
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(marketplace, LINTER, "name: linter\non: push\n")
        manifest = parse_manifest(
            {
                "source": "owner/ghwm-registry",
                "workflows": [{"name": LINTER, "version": VERSION_1}],
            }
        )
        empty_manifest = parse_manifest({"source": MARKETPLACE_SOURCE, "workflows": []})
        install_workflows(consumer, manifest, local_path=marketplace)
        workflow_path = consumer / ".github" / "workflows" / "linter.yaml"
        workflow_path.write_text("name: custom\n")

        result = install_workflows(consumer, empty_manifest, local_path=marketplace)
        lockfile = read_lockfile(consumer)

        assert result.pruned == []
        assert result.skipped == [(LINTER, "unmanaged")]
        assert workflow_path.is_file()
        assert lockfile.find("linter") is not None

    def test_install_workflows_should_skip_pruning_when_stale_workflow_file_is_modified(self, tmp_path: Path) -> None:
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(marketplace, LINTER, "name: linter\non: push\n")
        manifest = parse_manifest(
            {
                "source": "owner/ghwm-registry",
                "workflows": [{"name": LINTER, "version": VERSION_1}],
            }
        )
        empty_manifest = parse_manifest({"source": MARKETPLACE_SOURCE, "workflows": []})
        install_workflows(consumer, manifest, local_path=marketplace)
        workflow_path = consumer / ".github" / "workflows" / "linter.yaml"
        workflow_path.write_text(
            workflow_path.read_text().replace("name: linter", "name: modified"),
            encoding="utf-8",
        )

        result = install_workflows(consumer, empty_manifest, local_path=marketplace)
        lockfile = read_lockfile(consumer)

        assert result.pruned == []
        assert result.skipped == [(LINTER, "modified")]
        assert workflow_path.is_file()
        assert lockfile.find("linter") is not None


class TestTelemetry:
    def test_install_workflows_should_emit_install_and_run_events_when_registry_is_public(self, tmp_path: Path) -> None:
        # Arrange
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(marketplace, LINTER, "name: linter\non: push\n")
        manifest = _marketplace_manifest([{"name": LINTER, "version": VERSION_1_2_3}])

        # Act
        with (
            patch("ghwm.install.is_public_repository", return_value=True),
            patch("ghwm.install.track_installation") as mock_track,
        ):
            install_workflows(consumer, manifest, local_path=marketplace)

        # Assert
        calls = [(c.kwargs["event_type"], c.kwargs["workflow_name"]) for c in mock_track.call_args_list]
        assert ("install", LINTER) in calls
        assert ("run", LINTER) in calls

    def test_install_workflows_should_not_emit_telemetry_when_registry_is_private(self, tmp_path: Path) -> None:
        # Arrange
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(marketplace, LINTER, "name: linter\non: push\n")
        manifest = _marketplace_manifest([{"name": LINTER, "version": VERSION_1_2_3}])

        # Act
        with (
            patch("ghwm.install.is_public_repository", return_value=False),
            patch("ghwm.install.track_installation") as mock_track,
        ):
            install_workflows(consumer, manifest, local_path=marketplace)

        # Assert
        mock_track.assert_not_called()

    def test_install_workflows_should_not_emit_telemetry_when_no_telemetry_is_true(self, tmp_path: Path) -> None:
        # Arrange
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(marketplace, LINTER, "name: linter\non: push\n")
        manifest = _marketplace_manifest([{"name": LINTER, "version": VERSION_1_2_3}])

        # Act
        with (
            patch("ghwm.install.is_public_repository") as mock_check,
            patch("ghwm.install.track_installation") as mock_track,
        ):
            install_workflows(consumer, manifest, local_path=marketplace, no_telemetry=True)

        # Assert
        mock_check.assert_not_called()
        mock_track.assert_not_called()

    def test_install_workflows_should_emit_only_run_event_when_workflow_is_already_up_to_date(
        self, tmp_path: Path
    ) -> None:
        # Arrange
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(marketplace, LINTER, "name: linter\non: push\n")
        manifest = _marketplace_manifest([{"name": LINTER, "version": VERSION_1_2_3}])

        with patch("ghwm.install.is_public_repository", return_value=True):
            install_workflows(consumer, manifest, local_path=marketplace)

        # Act: second run — workflow is already up to date (skipped, not installed/updated)
        with (
            patch("ghwm.install.is_public_repository", return_value=True),
            patch("ghwm.install.track_installation") as mock_track,
        ):
            install_workflows(consumer, manifest, local_path=marketplace)

        # Assert
        event_types = [c.kwargs["event_type"] for c in mock_track.call_args_list]
        assert "install" not in event_types
        assert "run" not in event_types

    def test_update_workflows_should_emit_run_event_but_not_install_event_when_workflow_is_updated(
        self, tmp_path: Path
    ) -> None:
        # Arrange
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(
            marketplace,
            LINTER,
            "name: v1\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n",
        )
        manifest = _marketplace_manifest([{"name": LINTER, "version": VERSION_1_2_3}])

        with patch("ghwm.install.is_public_repository", return_value=True):
            install_workflows(consumer, manifest, local_path=marketplace)

        _write_marketplace_package(
            marketplace,
            LINTER,
            "name: v2\non: push\njobs:\n  test:\n    runs-on: ubuntu-latest\n",
        )

        # Act
        with (
            patch("ghwm.install.is_public_repository", return_value=True),
            patch("ghwm.install.track_installation") as mock_track,
        ):
            update_workflows(consumer, manifest, local_path=marketplace)

        # Assert
        event_types = [c.kwargs["event_type"] for c in mock_track.call_args_list]
        assert "run" in event_types
        assert "install" not in event_types

    def test_install_workflows_should_include_version_in_telemetry_event(self, tmp_path: Path) -> None:
        # Arrange
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(marketplace, LINTER, "name: linter\non: push\n")
        manifest = _marketplace_manifest([{"name": LINTER, "version": VERSION_1_2_3}])

        # Act
        with (
            patch("ghwm.install.is_public_repository", return_value=True),
            patch("ghwm.install.track_installation") as mock_track,
        ):
            install_workflows(consumer, manifest, local_path=marketplace)

        # Assert
        install_call = next(c for c in mock_track.call_args_list if c.kwargs["event_type"] == "install")
        assert install_call.kwargs["version"] == VERSION_1_2_3
        assert install_call.kwargs["source"] == MARKETPLACE_SOURCE

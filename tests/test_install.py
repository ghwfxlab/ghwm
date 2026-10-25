"""Tests for ghwm.install."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

from ghwm.download import WorkflowSource
from ghwm.download_npm import InstalledFile
from ghwm.install import InstallResult, _emit_telemetry, install_workflows, update_workflows
from ghwm.lock import read_lockfile
from ghwm.managed_files import extract_body, load_workflow_yaml
from ghwm.manifest import Manifest, WorkflowEntry, parse_manifest
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


def _sha256_of_body(installed_path: Path) -> str:
    body = extract_body(installed_path.read_text(encoding="utf-8"))
    return f"sha256:{hashlib.sha256(f'{body.rstrip()}\n'.encode()).hexdigest()}"


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


@dataclass(frozen=True)
class _UpdateOption:
    """A workflow section that `update-*` controls: keep the local value or take the packaged one."""

    manifest_key: str
    cli_kwarg: str
    v1_content: str
    local_edit: tuple[str, str]
    v2_content: str
    section: Callable[[dict[str, Any]], object]
    local_value: object
    packaged_value: object


TRIGGERS = _UpdateOption(
    manifest_key="update-triggers",
    cli_kwarg="update_triggers",
    v1_content="name: v1\non:\n  push:\n    branches:\n      - main\n",
    local_edit=("- main", "- release/*"),
    v2_content="name: v2\non:\n  pull_request:\n",
    section=lambda body: body["on"],
    local_value={"push": {"branches": ["release/*"]}},
    packaged_value={"pull_request": None},
)
ENVS = _UpdateOption(
    manifest_key="update-envs",
    cli_kwarg="update_envs",
    v1_content="name: v1\nenv:\n  MY_VAR: old\n",
    local_edit=("MY_VAR: old", "MY_VAR: consumer_changed"),
    v2_content="name: v2\nenv:\n  MY_VAR: new\n",
    section=lambda body: body["env"],
    local_value={"MY_VAR": "consumer_changed"},
    packaged_value={"MY_VAR": "new"},
)
RUNS_ON = _UpdateOption(
    manifest_key="update-runs-on",
    cli_kwarg="update_runs_on",
    v1_content="name: v1\njobs:\n  build:\n    runs-on: ubuntu-latest\n",
    local_edit=("ubuntu-latest", "self-hosted"),
    v2_content="name: v2\njobs:\n  build:\n    runs-on: ubuntu-24.04\n",
    section=lambda body: body["jobs"]["build"]["runs-on"],
    local_value="self-hosted",
    packaged_value="ubuntu-24.04",
)
UPDATE_OPTIONS = [
    pytest.param(TRIGGERS, id="triggers"),
    pytest.param(ENVS, id="envs"),
    pytest.param(RUNS_ON, id="runs-on"),
]


def _install_with_local_edit(
    tmp_path: Path, option: _UpdateOption, workflow_entry: Mapping[str, object]
) -> tuple[Path, Path, Manifest, Path]:
    """Install v1, edit the option's section locally, then publish v2 upstream."""
    marketplace = tmp_path / "marketplace"
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    _write_marketplace_package(marketplace, LINTER, option.v1_content)
    manifest = parse_manifest(
        {"source": "owner/ghwm-registry", "workflows": [{"name": LINTER, "version": VERSION_1, **workflow_entry}]}
    )
    install_workflows(consumer, manifest, local_path=marketplace)

    installed_path = _workflow_path(consumer, LINTER)
    old, new = option.local_edit
    installed_path.write_text(installed_path.read_text().replace(old, new), encoding="utf-8")
    _write_marketplace_package(marketplace, LINTER, option.v2_content)
    return marketplace, consumer, manifest, installed_path


def _read_section(option: _UpdateOption, installed_path: Path) -> object:
    body = cast(dict[str, Any], load_workflow_yaml(extract_body(installed_path.read_text())))
    return option.section(body)


def _installed_name(installed_path: Path) -> object:
    body = cast(dict[str, object], load_workflow_yaml(extract_body(installed_path.read_text())))
    return body["name"]


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
            load_workflow_yaml(extract_body(installed_path.read_text())),
        )
        assert body["on"] == "pull_request"

    @pytest.mark.parametrize("option", UPDATE_OPTIONS)
    @pytest.mark.parametrize("explicit_false", [False, True], ids=["unset", "false"])
    def test_update_workflows_should_preserve_local_section_when_update_option_is_false_or_unset(
        self, tmp_path: Path, option: _UpdateOption, explicit_false: bool
    ) -> None:
        # Arrange
        entry = {option.manifest_key: False} if explicit_false else {}
        marketplace, consumer, manifest, installed_path = _install_with_local_edit(tmp_path, option, entry)

        # Act
        result = update_workflows(consumer, manifest, local_path=marketplace)

        # Assert
        assert _installed_name(installed_path) == "v2"
        assert _read_section(option, installed_path) == option.local_value
        assert result.updated == [LINTER]

    @pytest.mark.parametrize("option", UPDATE_OPTIONS)
    def test_update_workflows_should_replace_local_section_when_manifest_requests_override(
        self, tmp_path: Path, option: _UpdateOption
    ) -> None:
        # Arrange
        marketplace, consumer, manifest, installed_path = _install_with_local_edit(
            tmp_path, option, {option.manifest_key: True}
        )

        # Act
        update_workflows(consumer, manifest, local_path=marketplace)

        # Assert
        assert _installed_name(installed_path) == "v2"
        assert _read_section(option, installed_path) == option.packaged_value

    @pytest.mark.parametrize("option", UPDATE_OPTIONS)
    @pytest.mark.parametrize("explicit_false", [False, True], ids=["unset", "false"])
    def test_update_workflows_should_replace_local_section_when_run_requests_global_override(
        self, tmp_path: Path, option: _UpdateOption, explicit_false: bool
    ) -> None:
        # Arrange
        entry = {option.manifest_key: False} if explicit_false else {}
        marketplace, consumer, manifest, installed_path = _install_with_local_edit(tmp_path, option, entry)

        # Act
        update_workflows(consumer, manifest, local_path=marketplace, **{option.cli_kwarg: True})

        # Assert
        assert _read_section(option, installed_path) == option.packaged_value

    def test_install_workflows_should_use_packaged_runs_on_when_workflow_is_installed_for_the_first_time(
        self, tmp_path: Path
    ) -> None:
        # Arrange
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(marketplace, LINTER, "name: v1\njobs:\n  build:\n    runs-on: ubuntu-24.04\n")
        manifest = parse_manifest(
            {"source": "owner/ghwm-registry", "workflows": [{"name": LINTER, "version": VERSION_1}]}
        )

        # Act
        install_workflows(consumer, manifest, local_path=marketplace)

        # Assert
        assert _read_section(RUNS_ON, consumer / ".github" / "workflows" / "linter.yaml") == "ubuntu-24.04"

    def test_update_workflows_should_report_up_to_date_and_keep_hash_consistent_when_runs_on_is_preserved(
        self, tmp_path: Path
    ) -> None:
        # Arrange
        marketplace, consumer, manifest, installed_path = _install_with_local_edit(tmp_path, RUNS_ON, {})
        update_workflows(consumer, manifest, local_path=marketplace)

        # Act
        second = update_workflows(consumer, manifest, local_path=marketplace)

        # Assert
        assert second.updated == []
        assert second.skipped == [(LINTER, "already up to date")]
        lock_file = read_lockfile(consumer).packages[0].files[0]
        assert f"# Hash: {lock_file.source_hash}" in installed_path.read_text()
        assert _sha256_of_body(installed_path) == lock_file.source_hash

    def test_install_workflows_should_not_prune_as_modified_when_runs_on_was_preserved(self, tmp_path: Path) -> None:
        # Arrange
        marketplace, consumer, manifest, installed_path = _install_with_local_edit(tmp_path, RUNS_ON, {})
        update_workflows(consumer, manifest, local_path=marketplace)
        empty_manifest = parse_manifest({"source": "owner/ghwm-registry", "workflows": []})

        # Act
        result = install_workflows(consumer, empty_manifest, local_path=marketplace)

        # Assert
        assert result.pruned == [LINTER]
        assert not installed_path.exists()

    def test_update_workflows_should_report_notice_when_preserved_job_no_longer_exists_upstream(
        self, tmp_path: Path
    ) -> None:
        # Arrange
        marketplace, consumer, manifest, _ = _install_with_local_edit(tmp_path, RUNS_ON, {})
        _write_marketplace_package(marketplace, LINTER, "name: v2\njobs:\n  renamed:\n    runs-on: ubuntu-24.04\n")

        # Act
        result = update_workflows(consumer, manifest, local_path=marketplace)

        # Assert
        assert result.notices == [f"{LINTER}: job 'build' no longer exists upstream; its local runs-on was not kept"]

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
    def test_install_workflows_should_emit_install_event_when_registry_is_public(self, tmp_path: Path) -> None:
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
        calls = [(call.kwargs["event_type"], call.kwargs["workflow_name"]) for call in mock_track.call_args_list]
        assert ("install", LINTER) in calls
        assert len(mock_track.call_args_list) == 1

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

    def test_install_workflows_should_not_emit_telemetry_when_telemetry_is_disabled_via_env(
        self, tmp_path: Path
    ) -> None:
        # Arrange
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(marketplace, LINTER, "name: linter\non: push\n")
        manifest = _marketplace_manifest([{"name": LINTER, "version": VERSION_1_2_3}])

        # Act
        with (
            patch.dict(os.environ, {"GHWM_NO_TELEMETRY": "1"}),
            patch("ghwm.install.is_public_repository") as mock_check,
            patch("ghwm.install.track_installation") as mock_track,
        ):
            install_workflows(consumer, manifest, local_path=marketplace)

        # Assert
        mock_check.assert_not_called()
        mock_track.assert_not_called()

    def test_emit_telemetry_should_return_early_when_telemetry_is_disabled(self) -> None:
        # Arrange
        manifest = _marketplace_manifest([{"name": LINTER, "version": VERSION_1_2_3}])
        result = InstallResult(installed=[LINTER], updated=[], pruned=[], skipped=[])

        # Act
        with (
            patch.dict(os.environ, {"DO_NOT_TRACK": "1"}),
            patch("ghwm.install.is_public_repository") as mock_check,
            patch("ghwm.install.track_installation") as mock_track,
        ):
            _emit_telemetry(MARKETPLACE_SOURCE, manifest, result)

        # Assert
        mock_check.assert_not_called()
        mock_track.assert_not_called()

    def test_install_workflows_should_not_emit_telemetry_when_source_has_no_slash(self, tmp_path: Path) -> None:
        # Arrange
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        manifest = Manifest(
            source="noslash",
            workflows=[WorkflowEntry(name=LINTER, version=VERSION_1_2_3, source="noslash")],
        )
        fake_source = WorkflowSource(
            name=LINTER,
            package_name=f"@scope/{LINTER}",
            files=[InstalledFile("main.yml", b"name: test\n", f".github/workflows/{LINTER}.yaml")],
        )

        # Act
        with (
            patch("ghwm.install.download_workflows", return_value=[fake_source]),
            patch("ghwm.install.is_public_repository") as mock_check,
            patch("ghwm.install.track_installation") as mock_track,
        ):
            install_workflows(consumer, manifest)

        # Assert: guard returns early without calling anything
        mock_check.assert_not_called()
        mock_track.assert_not_called()

    def test_install_workflows_should_not_emit_any_telemetry_when_workflow_is_already_up_to_date(
        self, tmp_path: Path
    ) -> None:
        # Arrange
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(marketplace, LINTER, "name: linter\non: push\n")
        manifest = _marketplace_manifest([{"name": LINTER, "version": VERSION_1_2_3}])

        with (
            patch("ghwm.install.is_public_repository", return_value=True),
            patch("ghwm.install.track_installation"),
        ):
            install_workflows(consumer, manifest, local_path=marketplace)

        # Act: second run — workflow is already up to date (skipped, not installed/updated)
        with (
            patch("ghwm.install.is_public_repository", return_value=True),
            patch("ghwm.install.track_installation") as mock_track,
        ):
            install_workflows(consumer, manifest, local_path=marketplace)

        # Assert
        event_types = [call.kwargs["event_type"] for call in mock_track.call_args_list]
        assert "install" not in event_types
        assert "run" not in event_types

    def test_update_workflows_should_emit_updated_event_but_not_install_event_when_workflow_is_updated(
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

        with (
            patch("ghwm.install.is_public_repository", return_value=True),
            patch("ghwm.install.track_installation"),
        ):
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
        event_types = [call.kwargs["event_type"] for call in mock_track.call_args_list]
        assert "updated" in event_types
        assert "install" not in event_types

    def test_install_workflows_should_include_version_in_telemetry_event_when_workflow_is_installed(
        self, tmp_path: Path
    ) -> None:
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
        install_call = next(call for call in mock_track.call_args_list if call.kwargs["event_type"] == "install")
        assert install_call.kwargs["version"] == VERSION_1_2_3
        assert install_call.kwargs["source"] == MARKETPLACE_SOURCE
        assert install_call.kwargs["metadata"]["version"] == VERSION_1_2_3
        assert install_call.kwargs["metadata"]["source"] == MARKETPLACE_SOURCE

    def test_install_workflows_should_include_enriched_metadata_in_telemetry_when_package_has_frontmatter(
        self, tmp_path: Path
    ) -> None:
        # Arrange
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        manifest_content = (
            "# ---\n"
            "# title: Super Linter\n"
            "# description: Lint all the things\n"
            "# tags:\n"
            "#   - lint\n"
            "#   - ci\n"
            "# icon: fact_check\n"
            "# owner: custom-owner\n"
            "# ---\n"
            "name: linter\n"
            "files:\n"
            "  - source: linter.yaml\n"
            "    target: .github/workflows/linter.yaml\n"
        )
        _write_marketplace_package(marketplace, LINTER, "name: linter\non: push\n")
        (marketplace / "workflows" / LINTER / "workflow.yml").write_text(manifest_content)
        manifest = _marketplace_manifest([{"name": LINTER, "version": VERSION_1_2_3}])

        # Act
        with (
            patch("ghwm.install.is_public_repository", return_value=True),
            patch("ghwm.install.track_installation") as mock_track,
        ):
            install_workflows(consumer, manifest, local_path=marketplace)

        # Assert
        install_call = next(call for call in mock_track.call_args_list if call.kwargs["event_type"] == "install")
        meta = install_call.kwargs["metadata"]
        assert meta["title"] == "Super Linter"
        assert meta["description"] == "Lint all the things"
        assert meta["tags"] == ["lint", "ci"]
        assert meta["icon"] == "fact_check"
        assert meta["owner"] == "custom-owner"
        assert meta["source"] == MARKETPLACE_SOURCE

    def test_install_workflows_should_isolate_mixed_manifest_and_never_leak_private_workflow_when_registry_is_private(
        self, tmp_path: Path
    ) -> None:
        # Arrange
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(marketplace, LINTER, "name: linter\non: push\n")
        _write_marketplace_package(marketplace, "private-flow", "name: private-flow\non: push\n")

        manifest = Manifest(
            source=MARKETPLACE_SOURCE,
            workflows=[
                WorkflowEntry(name=LINTER, version="1.0.0"),
                WorkflowEntry(name="private-flow", version="2.0.0", source="private-org/private-repo"),
            ],
        )

        def mock_visibility(owner: str, repo: str) -> bool:
            return owner != "private-org"

        # Act
        with (
            patch("ghwm.install.is_public_repository", side_effect=mock_visibility),
            patch("ghwm.install.track_installation") as mock_track,
        ):
            install_workflows(consumer, manifest, local_path=marketplace)

        # Assert: ONLY linter was tracked; private-flow was strictly isolated (zero calls)
        assert len(mock_track.call_args_list) == 1
        call_kwargs = mock_track.call_args_list[0].kwargs
        assert call_kwargs["workflow_name"] == LINTER
        assert call_kwargs["source"] == MARKETPLACE_SOURCE
        tracked_names = [call.kwargs["workflow_name"] for call in mock_track.call_args_list]
        assert "private-flow" not in tracked_names

    def test_install_workflows_should_track_against_overridden_source_when_workflow_specifies_custom_source(
        self, tmp_path: Path
    ) -> None:
        # Arrange
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(marketplace, LINTER, "name: linter\non: push\n")
        custom_source = "custom-owner/community-workflows"
        manifest = Manifest(
            source="default-owner/default-repo",
            workflows=[
                WorkflowEntry(name=LINTER, version="1.0.0", source=custom_source),
            ],
        )

        # Act
        with (
            patch("ghwm.install.is_public_repository", return_value=True) as mock_public,
            patch("ghwm.install.track_installation") as mock_track,
        ):
            install_workflows(consumer, manifest, local_path=marketplace)

        # Assert: Verified against custom-owner/community-workflows, not default-owner/default-repo
        mock_public.assert_called_once_with("custom-owner", "community-workflows")
        assert len(mock_track.call_args_list) == 1
        assert mock_track.call_args_list[0].kwargs["source"] == custom_source
        assert mock_track.call_args_list[0].kwargs["metadata"]["source"] == custom_source

    def test_install_workflows_should_suppress_unexpected_telemetry_exceptions_when_failure_occurs(
        self, tmp_path: Path
    ) -> None:
        # Arrange
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_marketplace_package(marketplace, LINTER, "name: linter\non: push\n")
        manifest = _marketplace_manifest([{"name": LINTER, "version": VERSION_1_2_3}])

        # Act & Assert: unexpected telemetry exception must not fail the install
        with (
            patch("ghwm.install.is_public_repository", return_value=True),
            patch("ghwm.install.track_installation", side_effect=RuntimeError("telemetry server down")),
        ):
            result = install_workflows(consumer, manifest, local_path=marketplace)

        assert result.installed == [LINTER]

"""Tests for ghwm.manifest."""

from __future__ import annotations

from pathlib import Path

import pytest

from ghwm.manifest import Manifest, WorkflowEntry, parse_manifest, parse_spec, read_manifest
from tests.shared import AUTO_ASSIGN_PR, LINTER, MARKETPLACE_SOURCE, VERSION_1, VERSION_2


class TestParseSpec:
    def test_parse_spec_should_split_scoped_name_and_version_when_spec_includes_version(self) -> None:
        assert parse_spec(f"@owner/{LINTER}@0.1.4") == (f"@owner/{LINTER}", "0.1.4")

    def test_parse_spec_should_keep_name_when_spec_omits_version(self) -> None:
        assert parse_spec(LINTER) == (LINTER, None)

    def test_parse_spec_should_treat_suffix_as_name_when_version_contains_slash(self) -> None:
        assert parse_spec(f"{LINTER}@feature/my-branch") == (f"{LINTER}@feature/my-branch", None)


class TestParseManifest:
    def test_parse_manifest_should_parse_object_entry_with_update_flags_when_workflow_entry_includes_update_flags(
        self,
    ) -> None:
        manifest = parse_manifest(
            {
                "source": MARKETPLACE_SOURCE,
                "workflows": [
                    {
                        "name": AUTO_ASSIGN_PR,
                        "version": VERSION_1,
                        "update-triggers": True,
                        "update-config-files": True,
                    }
                ],
            }
        )

        entry = manifest.workflows[0]
        assert entry.name == AUTO_ASSIGN_PR
        assert entry.version == VERSION_1
        assert entry.update_triggers is True
        assert entry.update_config_files is True

    def test_parse_manifest_should_set_target_when_entry_includes_target_override(self) -> None:
        manifest = parse_manifest({"workflows": [{"name": LINTER, "version": VERSION_1, "target": "custom.yml"}]})

        assert manifest.workflows[0].target == "custom.yml"

    def test_parse_manifest_should_accept_mixed_entry_types_when_manifest_contains_strings_and_mappings(
        self,
    ) -> None:
        manifest = parse_manifest({"workflows": [f"{LINTER}@{VERSION_1}", {"name": "deploy", "version": VERSION_2}]})

        assert [entry.name for entry in manifest.workflows] == [LINTER, "deploy"]

    def test_parse_manifest_should_raise_value_error_when_workflows_key_is_missing(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            parse_manifest({})

        assert "'workflows' list" in str(exc_info.value)

    def test_parse_manifest_should_raise_value_error_when_workflow_entry_has_invalid_type(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            parse_manifest({"workflows": [123]})

        assert "Invalid entry" in str(exc_info.value)

    def test_parse_manifest_should_raise_value_error_when_workflow_names_are_duplicated(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            parse_manifest({"workflows": [f"{LINTER}@{VERSION_1}", f"{LINTER}@{VERSION_2}"]})

        assert "Duplicate" in str(exc_info.value)

    def test_parse_manifest_should_raise_value_error_when_update_triggers_is_not_boolean(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            parse_manifest({"workflows": [{"name": LINTER, "version": VERSION_1, "update-triggers": "yes"}]})

        assert "update-triggers" in str(exc_info.value)

    def test_parse_manifest_should_raise_value_error_when_update_config_files_is_not_boolean(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            parse_manifest({"workflows": [{"name": LINTER, "version": VERSION_1, "update-config-files": "yes"}]})

        assert "update-config-files" in str(exc_info.value)


class TestWorkflowEntry:
    def test_workflow_entry_should_return_version_as_resolved_ref_when_version_is_present(self) -> None:
        workflow_entry = WorkflowEntry(name="x", version=VERSION_1)

        assert workflow_entry.resolved_ref == VERSION_1

    def test_workflow_entry_should_default_resolved_ref_to_main_when_version_is_missing(self) -> None:
        workflow_entry = WorkflowEntry(name="x")

        assert workflow_entry.resolved_ref == "main"

    def test_workflow_entry_should_include_version_in_install_spec_when_version_is_present(self) -> None:
        workflow_entry = WorkflowEntry(name=LINTER, version=VERSION_1)

        assert workflow_entry.install_spec == f"{LINTER}@{VERSION_1}"


class TestManifest:
    def test_manifest_should_derive_npm_org_from_source_when_source_is_github_repository(self) -> None:
        manifest = Manifest(source=MARKETPLACE_SOURCE)

        assert manifest.npm_org == "owner"
        assert manifest.package_name(LINTER) == f"@owner/ghwm-{LINTER}"


class TestReadManifest:
    def test_read_manifest_should_load_manifest_when_default_manifest_file_exists(self, tmp_path: Path) -> None:
        (tmp_path / "ghwm.yml").write_text(f"workflows:\n  - {LINTER}@{VERSION_1}\n")

        manifest = read_manifest(tmp_path)

        assert manifest.workflows[0].name == LINTER
        assert manifest.workflows[0].version == VERSION_1

    def test_read_manifest_should_raise_file_not_found_when_manifest_file_is_missing(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError) as exc_info:
            read_manifest(tmp_path)

        assert "Manifest not found" in str(exc_info.value)

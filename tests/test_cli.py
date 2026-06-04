"""Tests for ghwm.cli."""

from __future__ import annotations

from pathlib import Path

import pytest

from ghwm import __version__
from ghwm.cli import build_parser, main, print_result
from ghwm.install import InstallResult
from tests.shared import AUTO_ASSIGN_PR, DEFAULT_MANIFEST_PATH, LINTER, WORKFLOWS_DIR

DEFAULT_WORKFLOW_CONTENT = "name: test\non: push\n"


def _workflow_file_path(consumer: Path, name: str) -> Path:
    return consumer / WORKFLOWS_DIR / f"{name}.yml"


def _setup_marketplace(root: Path, name: str, content: str = DEFAULT_WORKFLOW_CONTENT) -> None:
    workflow_dir = root / "workflows" / name
    workflow_dir.mkdir(parents=True)
    (workflow_dir / f"{name}.yml").write_text(content)
    (workflow_dir / "workflow.yml").write_text(
        f"name: {name}\nfiles:\n  - source: {name}.yml\n    target: .github/workflows/{name}.yml\n"
    )


def _write_manifest(cwd: Path, workflows: list[str], source: str | None = None) -> None:
    lines = ""
    if source:
        lines += f"source: {source}\n"
    if workflows:
        lines += "workflows:\n" + "".join(f"  - {workflow_entry}\n" for workflow_entry in workflows)
    else:
        lines += "workflows: []\n"
    (cwd / DEFAULT_MANIFEST_PATH).write_text(lines)


class TestBuildParser:
    def test_build_parser_should_set_install_command_when_install_subcommand_is_used(self) -> None:
        # Arrange
        parser = build_parser()

        # Act
        parsed_args = parser.parse_args(["install"])

        # Assert
        assert parsed_args.command == "install"

    def test_build_parser_should_set_update_command_when_update_subcommand_is_used(self) -> None:
        # Arrange
        parser = build_parser()

        # Act
        parsed_args = parser.parse_args(["update"])

        # Assert
        assert parsed_args.command == "update"

    def test_build_parser_should_set_list_command_when_list_subcommand_is_used(self) -> None:
        # Arrange
        parser = build_parser()

        # Act
        parsed_args = parser.parse_args(["list"])

        # Assert
        assert parsed_args.command == "list"

    def test_build_parser_should_enable_force_when_install_force_flag_is_used(self) -> None:
        # Arrange
        parser = build_parser()

        # Act
        parsed_args = parser.parse_args(["install", "--force"])

        # Assert
        assert parsed_args.force is True

    def test_build_parser_should_enable_no_prune_when_install_no_prune_flag_is_used(self) -> None:
        # Arrange
        parser = build_parser()

        # Act
        parsed_args = parser.parse_args(["install", "--no-prune"])

        # Assert
        assert parsed_args.no_prune is True

    def test_build_parser_should_use_default_manifest_name_when_manifest_flag_is_omitted(self) -> None:
        # Arrange
        parser = build_parser()

        # Act
        parsed_args = parser.parse_args([])

        # Assert
        assert parsed_args.manifest == DEFAULT_MANIFEST_PATH

    def test_build_parser_should_leave_command_unset_when_no_subcommand_is_provided(self) -> None:
        # Arrange
        parser = build_parser()

        # Act
        parsed_args = parser.parse_args([])

        # Assert
        assert parsed_args.command is None
        assert (parsed_args.command or "install") == "install"

    def test_build_parser_should_use_custom_manifest_path_when_manifest_flag_is_provided(self) -> None:
        # Arrange
        parser = build_parser()

        # Act
        parsed_args = parser.parse_args(["install", "--manifest", "custom.yml"])

        # Assert
        assert parsed_args.manifest == "custom.yml"

    def test_build_parser_should_capture_local_path_when_local_flag_is_provided(self) -> None:
        # Arrange
        parser = build_parser()

        # Act
        parsed_args = parser.parse_args(["install", "--local", "/tmp/marketplace"])

        # Assert
        assert parsed_args.local == "/tmp/marketplace"

    def test_build_parser_should_enable_update_triggers_when_flag_is_used(self) -> None:
        # Arrange
        parser = build_parser()

        # Act
        parsed_args = parser.parse_args(["update", "--update-triggers"])

        # Assert
        assert parsed_args.update_triggers is True

    def test_build_parser_should_enable_prune_when_update_prune_flag_is_used(self) -> None:
        # Arrange
        parser = build_parser()

        # Act
        parsed_args = parser.parse_args(["update", "--prune"])

        # Assert
        assert parsed_args.prune is True


class TestPrintResult:
    def test_print_result_should_print_installed_entries_when_result_contains_installed_workflows(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange
        install_result = InstallResult(installed=[LINTER], updated=[], pruned=[], skipped=[])

        # Act
        print_result(install_result)
        output = capsys.readouterr().out

        # Assert
        assert f"✓ Installed {LINTER}" in output

    def test_print_result_should_print_updated_entries_when_result_contains_updated_workflows(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange
        install_result = InstallResult(installed=[], updated=[LINTER], pruned=[], skipped=[])

        # Act
        print_result(install_result)
        output = capsys.readouterr().out

        # Assert
        assert f"↻ Updated {LINTER}" in output

    def test_print_result_should_print_pruned_entries_when_result_contains_pruned_workflows(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange
        install_result = InstallResult(installed=[], updated=[], pruned=["old-wf"], skipped=[])

        # Act
        print_result(install_result)
        output = capsys.readouterr().out

        # Assert
        assert "✗ Pruned old-wf" in output

    def test_print_result_should_print_skip_reason_when_result_contains_skipped_workflows(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange
        install_result = InstallResult(
            installed=[],
            updated=[],
            pruned=[],
            skipped=[(LINTER, "already up to date")],
        )

        # Act
        print_result(install_result)
        output = capsys.readouterr().out

        # Assert
        assert f"⊘ Skipped {LINTER} (already up to date)" in output

    def test_print_result_should_print_all_sections_when_result_contains_mixed_actions(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange
        install_result = InstallResult(
            installed=["new-wf"],
            updated=["old-wf"],
            pruned=["stale-wf"],
            skipped=[("unchanged-wf", "already up to date")],
        )

        # Act
        print_result(install_result)
        output = capsys.readouterr().out

        # Assert
        assert "✓ Installed new-wf" in output
        assert "↻ Updated old-wf" in output
        assert "✗ Pruned stale-wf" in output
        assert "⊘ Skipped unchanged-wf" in output

    def test_print_result_should_print_nothing_when_result_is_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        # Arrange
        install_result = InstallResult(installed=[], updated=[], pruned=[], skipped=[])

        # Act
        print_result(install_result)
        output = capsys.readouterr().out

        # Assert
        assert output == ""


class TestMainVersion:
    def test_main_should_exit_zero_when_version_flag_is_used(self) -> None:
        # Arrange
        version_arguments = ["--version"]

        # Act
        with pytest.raises(SystemExit) as exc:
            main(version_arguments)

        # Assert
        assert exc.value.code == 0

    def test_main_should_print_version_when_version_flag_is_used(self, capsys: pytest.CaptureFixture[str]) -> None:
        # Arrange
        version_arguments = ["--version"]

        # Act
        with pytest.raises(SystemExit):
            main(version_arguments)
        captured_output = capsys.readouterr()

        # Assert
        assert __version__ in captured_output.out


class TestMainInstall:
    def test_main_should_install_workflow_when_install_uses_local_marketplace(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _setup_marketplace(marketplace, LINTER)
        _write_manifest(consumer, [LINTER])
        installed_workflow_path = _workflow_file_path(consumer, LINTER)

        # Act
        main(["install", "--cwd", str(consumer), "--local", str(marketplace)])
        output = capsys.readouterr().out

        # Assert
        assert installed_workflow_path.is_file()
        assert f"✓ Installed {LINTER}" in output

    def test_main_should_install_multiple_workflows_when_manifest_contains_multiple_entries(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        for workflow_name in (LINTER, AUTO_ASSIGN_PR):
            _setup_marketplace(marketplace, workflow_name)
        _write_manifest(consumer, [LINTER, AUTO_ASSIGN_PR])
        linter_workflow_path = _workflow_file_path(consumer, LINTER)
        auto_assign_pr_workflow_path = _workflow_file_path(consumer, AUTO_ASSIGN_PR)

        # Act
        main(["install", "--cwd", str(consumer), "--local", str(marketplace)])
        output = capsys.readouterr().out

        # Assert
        assert linter_workflow_path.is_file()
        assert auto_assign_pr_workflow_path.is_file()
        assert f"✓ Installed {LINTER}" in output
        assert f"✓ Installed {AUTO_ASSIGN_PR}" in output

    def test_main_should_skip_workflow_when_install_repeats_without_source_changes(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _setup_marketplace(marketplace, LINTER)
        _write_manifest(consumer, [LINTER])

        # Act
        main(["install", "--cwd", str(consumer), "--local", str(marketplace)])
        main(["install", "--cwd", str(consumer), "--local", str(marketplace)])
        output = capsys.readouterr().out

        # Assert
        assert f"⊘ Skipped {LINTER} (already up to date)" in output

    def test_main_should_keep_stale_workflow_when_install_uses_no_prune(self, tmp_path: Path) -> None:
        # Arrange
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _setup_marketplace(marketplace, LINTER)
        installed_workflow_path = _workflow_file_path(consumer, LINTER)

        _write_manifest(consumer, [LINTER])
        main(["install", "--cwd", str(consumer), "--local", str(marketplace)])

        # Act
        _write_manifest(consumer, [])
        main(["install", "--no-prune", "--cwd", str(consumer), "--local", str(marketplace)])

        # Assert
        assert installed_workflow_path.is_file()

    def test_main_should_prune_stale_workflow_when_install_runs_with_default_prune(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _setup_marketplace(marketplace, LINTER)
        installed_workflow_path = _workflow_file_path(consumer, LINTER)

        _write_manifest(consumer, [LINTER])
        main(["install", "--cwd", str(consumer), "--local", str(marketplace)])

        # Act
        _write_manifest(consumer, [])
        main(["install", "--cwd", str(consumer), "--local", str(marketplace)])
        output = capsys.readouterr().out

        # Assert
        assert not installed_workflow_path.is_file()
        assert f"✗ Pruned {LINTER}" in output


class TestMainUpdate:
    def test_main_should_report_updated_workflow_when_update_detects_source_change(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _setup_marketplace(marketplace, LINTER, "name: v1\non: push\n")
        _write_manifest(consumer, [LINTER])

        main(["install", "--cwd", str(consumer), "--local", str(marketplace)])

        # Act
        (marketplace / "workflows" / LINTER / f"{LINTER}.yml").write_text("name: v2\non: push\n")
        main(["update", "--cwd", str(consumer), "--local", str(marketplace)])
        output = capsys.readouterr().out

        # Assert
        assert f"↻ Updated {LINTER}" in output

    def test_main_should_write_new_content_when_update_detects_source_change(self, tmp_path: Path) -> None:
        # Arrange
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _setup_marketplace(marketplace, LINTER, "name: v1\non: push\n")
        _write_manifest(consumer, [LINTER])

        main(["install", "--cwd", str(consumer), "--local", str(marketplace)])

        # Act
        (marketplace / "workflows" / LINTER / f"{LINTER}.yml").write_text("name: v2\non: push\n")
        main(["update", "--cwd", str(consumer), "--local", str(marketplace)])
        installed_content = _workflow_file_path(consumer, LINTER).read_text()

        # Assert
        assert "name: v2" in installed_content

    def test_main_should_prune_stale_workflow_when_update_uses_prune(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange
        marketplace = tmp_path / "marketplace"
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _setup_marketplace(marketplace, LINTER)
        installed_workflow_path = _workflow_file_path(consumer, LINTER)

        _write_manifest(consumer, [LINTER])
        main(["install", "--cwd", str(consumer), "--local", str(marketplace)])

        # Act
        _write_manifest(consumer, [])
        main(["update", "--prune", "--cwd", str(consumer), "--local", str(marketplace)])
        output = capsys.readouterr().out

        # Assert
        assert not installed_workflow_path.is_file()
        assert f"✗ Pruned {LINTER}" in output


class TestMainErrorHandling:
    def test_main_should_exit_one_when_install_manifest_is_missing(self, tmp_path: Path) -> None:
        # Arrange
        install_arguments = ["install", "--cwd", str(tmp_path)]

        # Act
        with pytest.raises(SystemExit) as exc:
            main(install_arguments)

        # Assert
        assert exc.value.code == 1

    def test_main_should_exit_one_when_manifest_content_is_invalid(self, tmp_path: Path) -> None:
        # Arrange
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        (consumer / DEFAULT_MANIFEST_PATH).write_text(f"workflows:\n  - {LINTER}\n  - {LINTER}\n")
        install_arguments = ["install", "--cwd", str(consumer)]

        # Act
        with pytest.raises(SystemExit) as exc:
            main(install_arguments)

        # Assert
        assert exc.value.code == 1

    def test_main_should_print_error_to_stderr_when_command_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        (consumer / DEFAULT_MANIFEST_PATH).write_text(f"workflows:\n  - {LINTER}\n  - {LINTER}\n")

        # Act
        with pytest.raises(SystemExit):
            main(["install", "--cwd", str(consumer)])
        error_output = capsys.readouterr().err

        # Assert
        assert "Error:" in error_output


class TestMainModule:
    def test_module_entrypoint_should_exit_zero_when_invoked_with_version_flag(self) -> None:
        # Arrange
        import runpy
        import sys

        sys_argv_backup = sys.argv[:]
        sys.argv = ["ghwm", "--version"]

        # Act
        try:
            with pytest.raises(SystemExit) as exc:
                runpy.run_module("ghwm", run_name="__main__", alter_sys=True)
        finally:
            sys.argv = sys_argv_backup

        # Assert
        assert exc.value.code == 0


class TestMainList:
    def test_main_should_list_workflow_names_when_list_command_is_used(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_manifest(consumer, [LINTER, AUTO_ASSIGN_PR])

        # Act
        main(["list", "--cwd", str(consumer)])
        output = capsys.readouterr().out

        # Assert
        assert LINTER in output
        assert AUTO_ASSIGN_PR in output

    def test_main_should_list_workflow_version_when_manifest_entry_includes_version(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_manifest(consumer, [f"{LINTER}@0.1.4"])

        # Act
        main(["list", "--cwd", str(consumer)])
        output = capsys.readouterr().out

        # Assert
        assert f"{LINTER}@0.1.4" in output

    def test_main_should_show_source_repository_when_manifest_defines_source(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_manifest(consumer, [LINTER], source="myorg/myrepo")

        # Act
        main(["list", "--cwd", str(consumer)])
        output = capsys.readouterr().out

        # Assert
        assert "myorg/myrepo" in output

    def test_main_should_show_workflow_count_when_list_command_runs(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        _write_manifest(consumer, ["wf1", "wf2", "wf3"])

        # Act
        main(["list", "--cwd", str(consumer)])
        output = capsys.readouterr().out

        # Assert
        assert "3" in output

    def test_main_should_exit_one_when_list_manifest_is_missing(self, tmp_path: Path) -> None:
        # Arrange
        list_arguments = ["list", "--cwd", str(tmp_path)]

        # Act
        with pytest.raises(SystemExit) as exc:
            main(list_arguments)

        # Assert
        assert exc.value.code == 1

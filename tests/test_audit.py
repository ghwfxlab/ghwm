"""Tests for ghwm.audit module."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ghwm.audit import _get_findings, _run_zizmor, run_audit
from ghwm.lock import LockEntry, Lockfile, LockFileEntry, write_lockfile


class TestRunZizmor:
    def test_run_zizmor_should_fallback_to_uvx_when_zizmor_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Arrange
        calls: list[list[str]] = []

        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            if cmd[0] == "zizmor":
                raise FileNotFoundError("zizmor not found")
            return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

        monkeypatch.setattr(subprocess, "run", fake_run)

        # Act
        res = _run_zizmor(["file.yml"])

        # Assert
        assert res.returncode == 0
        assert len(calls) == 2
        assert calls[0][0] == "zizmor"
        assert calls[1][:2] == ["uvx", "zizmor"]

    def test_run_zizmor_should_raise_runtime_error_when_neither_zizmor_nor_uvx_found(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Arrange
        def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            raise FileNotFoundError("not found")

        monkeypatch.setattr(subprocess, "run", fake_run)

        # Act & Assert
        with pytest.raises(RuntimeError, match="zizmor linter is not installed and 'uvx' is not available"):
            _run_zizmor(["file.yml"])


class TestGetFindings:
    def test_get_findings_should_raise_runtime_error_when_zizmor_fails_with_nonzero_and_no_json(self) -> None:
        # Arrange
        proc = subprocess.CompletedProcess(["zizmor"], 1, stdout="fatal failure", stderr="")

        # Act & Assert
        with pytest.raises(RuntimeError, match="zizmor execution failed: fatal failure"):
            _get_findings(proc)

    def test_get_findings_should_raise_runtime_error_when_json_is_invalid_and_stderr_present(self) -> None:
        # Arrange
        proc = subprocess.CompletedProcess(["zizmor"], 0, stdout="invalid json", stderr="some error")

        # Act & Assert
        with pytest.raises(RuntimeError, match="zizmor execution failed: some error"):
            _get_findings(proc)

    def test_get_findings_should_return_empty_list_when_stdout_and_stderr_are_empty(self) -> None:
        # Arrange
        proc = subprocess.CompletedProcess(["zizmor"], 0, stdout="", stderr="")

        # Act
        findings = _get_findings(proc)

        # Assert
        assert findings == []


class TestRunAudit:
    def test_run_audit_should_exit_one_when_lockfile_has_no_packages(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        lock = Lockfile(packages=[])
        write_lockfile(consumer, lock)

        # Act
        with pytest.raises(SystemExit) as exc:
            run_audit(consumer)

        # Assert
        assert exc.value.code == 1
        assert "Error: No workflows installed" in capsys.readouterr().err

    def test_run_audit_should_print_message_and_return_when_no_workflow_files_exist_on_disk(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange
        consumer = tmp_path / "consumer"
        consumer.mkdir()
        lock = Lockfile(
            packages=[
                LockEntry(
                    name="linter",
                    version="1.0.0",
                    source="owner/repo",
                    files=[LockFileEntry(target=".github/workflows/missing.yml", source_hash="sha256:abc")],
                )
            ]
        )
        write_lockfile(consumer, lock)

        # Act
        run_audit(consumer)

        # Assert
        assert "No managed workflow files found to audit." in capsys.readouterr().out

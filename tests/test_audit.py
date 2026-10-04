"""Tests for ghwm.audit module."""

from __future__ import annotations

import json
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


@pytest.fixture
def audited_consumer(tmp_path: Path) -> Path:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    lock = Lockfile(
        packages=[
            LockEntry(
                name="linter",
                version="1.0.0",
                source="owner/repo",
                files=[LockFileEntry(target=".github/workflows/linter.yml", source_hash="sha256:abc")],
            )
        ]
    )
    write_lockfile(consumer, lock)
    wf_file = consumer / ".github" / "workflows" / "linter.yml"
    wf_file.parent.mkdir(parents=True, exist_ok=True)
    wf_file.write_text("name: linter\non: push\n")
    return consumer


class TestRunAudit:
    def test_run_audit_should_exit_one_when_lockfile_is_missing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # Arrange
        consumer = tmp_path / "consumer"
        consumer.mkdir()

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

    def test_run_audit_should_count_unknown_severity_as_low_and_exclude_ignored_findings(
        self, audited_consumer: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Arrange
        import sys

        findings = [
            {"ignored": True, "ident": "ignored-rule"},
            {
                "ident": "custom-rule",
                "desc": "custom rule finding",
                "determinations": {"severity": "CustomSeverity", "confidence": "Low"},
                "locations": [],
                "ignored": False,
            },
        ]
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **kw: subprocess.CompletedProcess([], 0, stdout=json.dumps(findings), stderr=""),
        )
        monkeypatch.setattr(sys.stdout, "isatty", lambda: False)

        # Act
        run_audit(audited_consumer)
        output = capsys.readouterr().out

        # Assert
        assert "ignored-rule" not in output
        assert "[CUSTOMSEVERITY] custom-rule: custom rule finding" in output
        assert "Location:   unknown location" in output
        assert "Security Score: 95/100" in output

    def test_run_audit_should_show_yellow_score_and_exit_one_when_medium_severity_finding_with_atty(
        self, audited_consumer: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Arrange
        import sys

        findings = [
            {
                "ident": "medium-rule",
                "desc": "medium severity finding",
                "determinations": {"severity": "Medium", "confidence": "High"},
                "locations": [],
                "ignored": False,
            }
        ]
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **kw: subprocess.CompletedProcess([], 0, stdout=json.dumps(findings), stderr=""),
        )
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

        # Act
        with pytest.raises(SystemExit) as exc:
            run_audit(audited_consumer)
        output = capsys.readouterr().out

        # Assert
        assert exc.value.code == 1
        assert "\033[33mSecurity Score: 90/100\033[0m" in output

    def test_run_audit_should_show_green_score_and_exit_zero_when_only_low_findings_with_atty(
        self, audited_consumer: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Arrange
        import sys

        findings = [
            {
                "ident": "low-rule",
                "desc": "low severity finding",
                "determinations": {"severity": "Low", "confidence": "Low"},
                "locations": [],
                "ignored": False,
            }
        ]
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **kw: subprocess.CompletedProcess([], 0, stdout=json.dumps(findings), stderr=""),
        )
        monkeypatch.setattr(sys.stdout, "isatty", lambda: True)

        # Act
        run_audit(audited_consumer)
        output = capsys.readouterr().out

        # Assert
        assert "\033[32mSecurity Score: 95/100\033[0m" in output

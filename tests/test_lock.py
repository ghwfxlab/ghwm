"""Tests for ghwm.lock."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ghwm.lock import LockEntry, Lockfile, LockFileEntry, read_lockfile, write_lockfile


class TestLockfile:
    def test_lockfile_should_return_entry_when_find_matches_existing_package(self) -> None:
        lockfile = Lockfile(
            packages=[
                LockEntry(
                    name="a",
                    version="1.0.0",
                    source="@owner/ghwm-a",
                    files=[LockFileEntry(target=".github/workflows/a.yml", source_hash="sha256:a")],
                )
            ]
        )

        entry = lockfile.find("a")

        assert entry is not None
        assert entry.version == "1.0.0"

    def test_lockfile_should_replace_entry_when_upsert_receives_existing_package_name(self) -> None:
        lockfile = Lockfile(
            packages=[
                LockEntry(
                    name="a",
                    version="1.0.0",
                    source="@owner/ghwm-a",
                    files=[LockFileEntry(target=".github/workflows/a.yml", source_hash="sha256:old")],
                )
            ]
        )

        lockfile.upsert(
            LockEntry(
                name="a",
                version="2.0.0",
                source="@owner/ghwm-a",
                files=[LockFileEntry(target=".github/workflows/a.yml", source_hash="sha256:new")],
            )
        )

        entry = lockfile.find("a")
        assert entry is not None
        assert entry.version == "2.0.0"
        assert entry.files[0].source_hash == "sha256:new"

    def test_lockfile_should_sort_packages_when_upsert_adds_multiple_entries(self) -> None:
        lockfile = Lockfile()

        lockfile.upsert(LockEntry("c", None, "@owner/ghwm-c", []))
        lockfile.upsert(LockEntry("a", None, "@owner/ghwm-a", []))

        assert [package_entry.name for package_entry in lockfile.packages] == ["a", "c"]

    def test_lock_entry_should_return_file_when_find_file_matches_target(self) -> None:
        entry = LockEntry(
            name="a",
            version="1.0.0",
            source="@owner/ghwm-a",
            files=[LockFileEntry(target=".github/workflows/a.yml", source_hash="sha256:a")],
        )

        file_entry = entry.find_file(".github/workflows/a.yml")

        assert file_entry is not None
        assert file_entry.source_hash == "sha256:a"


class TestReadLockfile:
    def test_read_lockfile_should_return_empty_lockfile_when_file_is_missing(self, tmp_path: Path) -> None:
        lockfile = read_lockfile(tmp_path)

        assert lockfile.packages == []

    def test_read_lockfile_should_load_packages_when_lockfile_exists(self, tmp_path: Path) -> None:
        data = {
            "lockfileVersion": 1,
            "packages": [
                {
                    "name": "auto-assign-pr",
                    "version": "1.0.0",
                    "source": "@owner/ghwm-auto-assign-pr",
                    "files": [
                        {
                            "target": ".github/workflows/auto-assign-pr.yaml",
                            "source_hash": "sha256:workflow",
                        },
                        {
                            "target": ".github/auto_assign.yaml",
                            "source_hash": "sha256:config",
                            "overwrite": False,
                        },
                    ],
                }
            ],
        }
        (tmp_path / "ghwm.lock").write_text(json.dumps(data))

        lockfile = read_lockfile(tmp_path)

        assert len(lockfile.packages) == 1
        assert lockfile.packages[0].name == "auto-assign-pr"
        assert lockfile.packages[0].files[1].overwrite is False

    def test_read_lockfile_should_raise_when_lockfile_version_is_not_supported(self, tmp_path: Path) -> None:
        (tmp_path / "ghwm.lock").write_text(json.dumps({"lockfileVersion": 2, "packages": []}))

        with pytest.raises(ValueError) as exc_info:
            read_lockfile(tmp_path)

        assert "regenerate" in str(exc_info.value)

    def test_read_lockfile_should_raise_when_package_files_are_missing(self, tmp_path: Path) -> None:
        (tmp_path / "ghwm.lock").write_text(
            json.dumps(
                {
                    "lockfileVersion": 1,
                    "packages": [{"name": "a", "source": "@owner/ghwm-a"}],
                }
            )
        )

        with pytest.raises(ValueError) as exc_info:
            read_lockfile(tmp_path)

        assert "regenerate" in str(exc_info.value)


class TestWriteLockfile:
    def test_write_lockfile_should_write_lockfile_when_packages_exist(self, tmp_path: Path) -> None:
        lockfile = Lockfile(
            packages=[
                LockEntry(
                    name="auto-assign-pr",
                    version="1.0.0",
                    source="@owner/ghwm-auto-assign-pr",
                    files=[
                        LockFileEntry(target=".github/workflows/auto-assign-pr.yaml", source_hash="sha256:wf"),
                        LockFileEntry(
                            target=".github/auto_assign.yaml",
                            source_hash="sha256:cfg",
                            overwrite=False,
                        ),
                    ],
                )
            ]
        )

        write_lockfile(tmp_path, lockfile)
        content = json.loads((tmp_path / "ghwm.lock").read_text())

        assert content["lockfileVersion"] == 1
        assert content["packages"][0]["source"] == "@owner/ghwm-auto-assign-pr"
        assert "overwrite" not in content["packages"][0]["files"][0]
        assert content["packages"][0]["files"][1]["overwrite"] is False

    def test_write_lockfile_should_delete_lockfile_when_packages_are_empty(self, tmp_path: Path) -> None:
        lock_path = tmp_path / "ghwm.lock"
        lock_path.write_text("{}")

        write_lockfile(tmp_path, Lockfile())

        assert not lock_path.exists()

    def test_write_lockfile_should_omit_none_fields_when_serializing_package(self, tmp_path: Path) -> None:
        lockfile = Lockfile(packages=[LockEntry("a", None, "@owner/ghwm-a", [LockFileEntry("t", "sha256:x")])])

        write_lockfile(tmp_path, lockfile)
        content = json.loads((tmp_path / "ghwm.lock").read_text())

        assert "version" not in content["packages"][0]

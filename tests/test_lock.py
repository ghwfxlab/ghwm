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

    def test_lockfile_should_remove_and_return_entry_when_remove_finds_existing_package(self) -> None:
        entry = LockEntry("a", None, "@owner/ghwm-a", [])
        lockfile = Lockfile(packages=[entry])

        removed = lockfile.remove("a")

        assert removed == entry
        assert lockfile.packages == []

    def test_lockfile_should_return_none_when_remove_does_not_find_package(self) -> None:
        lockfile = Lockfile(packages=[])

        removed = lockfile.remove("a")

        assert removed is None


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

    def test_read_lockfile_should_return_empty_packages_when_packages_field_is_not_a_list(self, tmp_path: Path) -> None:
        (tmp_path / "ghwm.lock").write_text(
            json.dumps(
                {
                    "lockfileVersion": 1,
                    "packages": None,
                }
            )
        )
        lockfile = read_lockfile(tmp_path)
        assert lockfile.packages == []

    def test_read_lockfile_should_raise_when_package_entry_is_not_a_dict(self, tmp_path: Path) -> None:
        (tmp_path / "ghwm.lock").write_text(
            json.dumps(
                {
                    "lockfileVersion": 1,
                    "packages": ["not_a_dict"],
                }
            )
        )
        with pytest.raises(ValueError) as exc_info:
            read_lockfile(tmp_path)
        assert "invalid package entry" in str(exc_info.value)

    def test_read_lockfile_should_raise_when_package_name_is_invalid(self, tmp_path: Path) -> None:
        (tmp_path / "ghwm.lock").write_text(
            json.dumps(
                {
                    "lockfileVersion": 1,
                    "packages": [
                        {
                            "source": "@owner/ghwm-a",
                            "files": [],
                        }
                    ],
                }
            )
        )
        with pytest.raises(ValueError) as exc_info:
            read_lockfile(tmp_path)
        assert "without a valid name" in str(exc_info.value)

    def test_read_lockfile_should_raise_when_package_source_is_invalid(self, tmp_path: Path) -> None:
        (tmp_path / "ghwm.lock").write_text(
            json.dumps(
                {
                    "lockfileVersion": 1,
                    "packages": [
                        {
                            "name": "a",
                            "files": [],
                        }
                    ],
                }
            )
        )
        with pytest.raises(ValueError) as exc_info:
            read_lockfile(tmp_path)
        assert "missing its source" in str(exc_info.value)

    def test_read_lockfile_should_raise_when_file_entry_is_not_a_dict(self, tmp_path: Path) -> None:
        (tmp_path / "ghwm.lock").write_text(
            json.dumps(
                {
                    "lockfileVersion": 1,
                    "packages": [
                        {
                            "name": "a",
                            "source": "@owner/ghwm-a",
                            "files": ["not_a_dict"],
                        }
                    ],
                }
            )
        )
        with pytest.raises(ValueError) as exc_info:
            read_lockfile(tmp_path)
        assert "invalid file entry" in str(exc_info.value)

    def test_read_lockfile_should_raise_when_file_entry_target_is_invalid(self, tmp_path: Path) -> None:
        (tmp_path / "ghwm.lock").write_text(
            json.dumps(
                {
                    "lockfileVersion": 1,
                    "packages": [
                        {
                            "name": "a",
                            "source": "@owner/ghwm-a",
                            "files": [{"source_hash": "sha256:hash"}],
                        }
                    ],
                }
            )
        )
        with pytest.raises(ValueError) as exc_info:
            read_lockfile(tmp_path)
        assert "without a valid target" in str(exc_info.value)

    def test_read_lockfile_should_raise_when_file_entry_source_hash_is_invalid(self, tmp_path: Path) -> None:
        (tmp_path / "ghwm.lock").write_text(
            json.dumps(
                {
                    "lockfileVersion": 1,
                    "packages": [
                        {
                            "name": "a",
                            "source": "@owner/ghwm-a",
                            "files": [{"target": "wf.yml"}],
                        }
                    ],
                }
            )
        )
        with pytest.raises(ValueError) as exc_info:
            read_lockfile(tmp_path)
        assert "without a valid source_hash" in str(exc_info.value)

    def test_read_lockfile_should_raise_when_file_entry_overwrite_is_not_boolean(self, tmp_path: Path) -> None:
        (tmp_path / "ghwm.lock").write_text(
            json.dumps(
                {
                    "lockfileVersion": 1,
                    "packages": [
                        {
                            "name": "a",
                            "source": "@owner/ghwm-a",
                            "files": [
                                {
                                    "target": "wf.yml",
                                    "source_hash": "sha256:hash",
                                    "overwrite": "not-a-bool",
                                }
                            ],
                        }
                    ],
                }
            )
        )
        with pytest.raises(ValueError) as exc_info:
            read_lockfile(tmp_path)
        assert "non-boolean overwrite value" in str(exc_info.value)


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

"""Manage ``ghwm.lock`` files."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_LOCKFILE = "ghwm.lock"
LOCKFILE_VERSION = 1


@dataclass
class LockFileEntry:
    """A single installed file tracked in the lockfile."""

    target: str
    source_hash: str
    overwrite: bool = True

    def to_dict(self) -> dict[str, str | bool]:
        data: dict[str, str | bool] = {
            "target": self.target,
            "source_hash": self.source_hash,
        }
        if not self.overwrite:
            data["overwrite"] = False
        return data


@dataclass
class LockEntry:
    """A single package entry in the lock file."""

    name: str
    version: str | None
    source: str
    files: list[LockFileEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": self.name,
            "source": self.source,
            "files": [file_entry.to_dict() for file_entry in self.files],
        }
        if self.version is not None:
            data["version"] = self.version
        return data

    def find_file(self, target: str) -> LockFileEntry | None:
        for file_entry in self.files:
            if file_entry.target == target:
                return file_entry
        return None


@dataclass
class Lockfile:
    """Parsed ``ghwm.lock``."""

    lockfile_version: int = LOCKFILE_VERSION
    packages: list[LockEntry] = field(default_factory=list)

    def find(self, name: str) -> LockEntry | None:
        for entry in self.packages:
            if entry.name == name:
                return entry
        return None

    def upsert(self, entry: LockEntry) -> None:
        self.packages = [package_entry for package_entry in self.packages if package_entry.name != entry.name]
        self.packages.append(entry)
        self.packages.sort(key=lambda package_entry: package_entry.name)

    def remove(self, name: str) -> LockEntry | None:
        removed = self.find(name)
        if removed:
            self.packages = [package_entry for package_entry in self.packages if package_entry.name != name]
        return removed


def _parse_file_entry(workflow_name: str, raw: Any) -> LockFileEntry:
    if not isinstance(raw, dict):
        raise ValueError(f"Lockfile package '{workflow_name}' contains an invalid file entry.")

    target = raw.get("target")
    source_hash = raw.get("source_hash")
    if not isinstance(target, str) or not target:
        raise ValueError(f"Lockfile package '{workflow_name}' contains a file entry without a valid target.")
    if not isinstance(source_hash, str) or not source_hash:
        raise ValueError(f"Lockfile package '{workflow_name}' contains a file entry without a valid source_hash.")

    overwrite_raw = raw.get("overwrite", True)
    if not isinstance(overwrite_raw, bool):
        raise ValueError(f"Lockfile package '{workflow_name}' contains a non-boolean overwrite value.")

    return LockFileEntry(target=target, source_hash=source_hash, overwrite=overwrite_raw)


def read_lockfile(cwd: Path, lockfile_path: str | None = None) -> Lockfile:
    """Read a ``ghwm.lock`` file, returning an empty lockfile if it doesn't exist."""
    file_path = cwd / (lockfile_path or DEFAULT_LOCKFILE)

    if not file_path.is_file():
        return Lockfile()

    data = json.loads(file_path.read_text(encoding="utf-8"))
    lockfile_version = data.get("lockfileVersion")
    if lockfile_version != LOCKFILE_VERSION:
        raise ValueError("Unsupported ghwm.lock format. Delete ghwm.lock and run `ghwm install` to regenerate it.")

    packages: list[LockEntry] = []
    for package_data in data.get("packages", []):
        if not isinstance(package_data, dict):
            raise ValueError("ghwm.lock contains an invalid package entry.")
        raw_files = package_data.get("files")
        if not isinstance(raw_files, list):
            raise ValueError("Unsupported ghwm.lock format. Delete ghwm.lock and run `ghwm install` to regenerate it.")
        workflow_name = package_data.get("name")
        source = package_data.get("source")
        if not isinstance(workflow_name, str) or not workflow_name:
            raise ValueError("ghwm.lock contains a package without a valid name.")
        if not isinstance(source, str) or not source:
            raise ValueError(f"Lockfile package '{workflow_name}' is missing its source.")
        packages.append(
            LockEntry(
                name=workflow_name,
                version=package_data.get("version"),
                source=source,
                files=[_parse_file_entry(workflow_name, raw_file) for raw_file in raw_files],
            )
        )

    return Lockfile(lockfile_version=lockfile_version, packages=packages)


def write_lockfile(cwd: Path, lockfile: Lockfile, lockfile_path: str | None = None) -> None:
    """Write the lock file. Deletes the file if no packages remain."""
    file_path = cwd / (lockfile_path or DEFAULT_LOCKFILE)

    if not lockfile.packages:
        file_path.unlink(missing_ok=True)
        return

    data = {
        "lockfileVersion": lockfile.lockfile_version,
        "packages": [package_entry.to_dict() for package_entry in lockfile.packages],
    }

    file_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

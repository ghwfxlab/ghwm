"""Parse ``ghwm.yml`` manifests."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ghwm.package_names import scoped_package_name

DEFAULT_MANIFEST = "ghwm.yml"
DEFAULT_SOURCE = "owner/ghwm-marketplace"
DEFAULT_REF = "main"


def _parse_optional_bool(raw: Any, *, field_name: str, index: int, default: bool = False) -> bool:
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    raise ValueError(f"Invalid entry at workflows[{index}]: '{field_name}' must be true or false.")


@dataclass(frozen=True)
class WorkflowEntry:
    """A single workflow declared in the manifest."""

    name: str
    version: str | None = None
    target: str | None = None
    update_triggers: bool = False
    update_config_files: bool = False

    @property
    def resolved_ref(self) -> str:
        """Return the package version to fetch, or the local-dev default."""
        return self.version or DEFAULT_REF

    @property
    def install_spec(self) -> str:
        """Human-readable spec string."""
        if self.version:
            return f"{self.name}@{self.version}"
        return self.name


@dataclass(frozen=True)
class Manifest:
    """Parsed ``ghwm.yml``."""

    source: str = DEFAULT_SOURCE
    workflows: list[WorkflowEntry] = field(default_factory=list)

    @property
    def npm_org(self) -> str:
        if "/" not in self.source:
            raise ValueError("ghwm.yml source must be in 'owner/repository' format.")
        return self.source.split("/", 1)[0]

    def package_name(self, workflow_name: str) -> str:
        return scoped_package_name(self.npm_org, workflow_name)


def _parse_entry(raw: Any, index: int) -> WorkflowEntry:
    if isinstance(raw, str):
        name, version = parse_spec(raw)
        return WorkflowEntry(name=name, version=version)

    if isinstance(raw, dict) and "name" in raw:
        parsed_name, inline_version = parse_spec(str(raw["name"]))
        version = raw.get("version") or inline_version
        target_raw = raw.get("target")
        target = str(target_raw).strip() if target_raw is not None else None
        update_triggers = _parse_optional_bool(
            raw.get("update-triggers"),
            field_name="update-triggers",
            index=index,
        )
        update_config_files = _parse_optional_bool(
            raw.get("update-config-files"),
            field_name="update-config-files",
            index=index,
        )
        return WorkflowEntry(
            name=parsed_name,
            version=version,
            target=target,
            update_triggers=update_triggers,
            update_config_files=update_config_files,
        )

    raise ValueError(f"Invalid entry at workflows[{index}]: expected a string or {{name: ...}}.")


def parse_spec(spec: str) -> tuple[str, str | None]:
    """Split ``name@version`` into ``(name, version)``."""
    trimmed = spec.strip()
    last_at = trimmed.rfind("@")

    if last_at > 0:
        name = trimmed[:last_at]
        version = trimmed[last_at + 1 :]
        if version and "/" not in version:
            return name, version

    return trimmed, None


def parse_manifest(data: Any) -> Manifest:
    """Parse a raw YAML dict into a :class:`Manifest`."""
    if not isinstance(data, dict):
        raise ValueError("ghwm.yml must be a YAML mapping.")

    workflows_raw = data.get("workflows")
    if not isinstance(workflows_raw, list):
        raise ValueError("ghwm.yml must contain a 'workflows' list.")

    source = str(data.get("source", DEFAULT_SOURCE)).strip()

    # Extracted logic
    entries = _validate_and_collect_entries(workflows_raw)

    return Manifest(source=source, workflows=entries)


def _validate_and_collect_entries(workflows_raw: list[Any]) -> list[WorkflowEntry]:
    """Ensures all workflow entries are unique and valid."""
    entries: list[WorkflowEntry] = []
    seen: set[str] = set()

    for index, raw in enumerate(workflows_raw):
        entry = _parse_entry(raw, index)

        if not entry.name:
            raise ValueError("Workflow name must be a non-empty string.")
        if entry.name in seen:
            raise ValueError(f"Duplicate workflow entry: {entry.name}")

        seen.add(entry.name)
        entries.append(entry)
    return entries


def read_manifest(cwd: Path, manifest_path: str | None = None) -> Manifest:
    """Read and parse a ``ghwm.yml`` file."""
    file_path = cwd / (manifest_path or DEFAULT_MANIFEST)

    if not file_path.is_file():
        raise FileNotFoundError(f"Manifest not found: {file_path}")

    data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
    return parse_manifest(data)

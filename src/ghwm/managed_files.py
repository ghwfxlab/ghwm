"""Manage installed workflow and config files."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from ghwm.download import WorkflowSource
from ghwm.download_npm import InstalledFile
from ghwm.lock import LockEntry, LockFileEntry
from ghwm.manifest import WorkflowEntry


class _WorkflowBlockedError(Exception):
    """Raised when a managed workflow file cannot be updated safely."""


class _GitHubActionsLoader(yaml.SafeLoader):
    """YAML loader that treats GitHub Actions keys like ``on`` as strings."""


_GitHubActionsLoader.yaml_implicit_resolvers = {
    key: value[:] for key, value in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
for key, resolvers in list(_GitHubActionsLoader.yaml_implicit_resolvers.items()):
    _GitHubActionsLoader.yaml_implicit_resolvers[key] = [
        resolver for resolver in resolvers if resolver[0] != "tag:yaml.org,2002:bool"
    ]
_GitHubActionsLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)  # type: ignore[no-untyped-call]


@dataclass
class _InstalledFileResult:
    changed: bool
    lock_file: LockFileEntry | None


def _sha256(content: str) -> str:
    return _sha256_bytes(content.encode("utf-8"))


def _sha256_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"


def _normalize_workflow_body(content: str) -> str:
    return f"{content.rstrip()}\n"


def _build_header(name: str, version: str | None, source: str, source_hash: str) -> str:
    version_str = version or "latest"
    return "\n".join(
        [
            f"# Managed by ghwm ({name}@{version_str})",
            f"# Source: {source}",
            f"# Hash: {source_hash}",
            "# Re-run `ghwm install` to refresh this file.",
        ]
    )


def _is_managed(content: str, name: str) -> bool:
    return content.startswith(f"# Managed by ghwm ({name}@")


def _is_workflow_target(target: str) -> bool:
    return target.startswith(".github/workflows/")


def _extract_body(content: str) -> str:
    """Strip the generated header, return the body."""
    lines = content.split("\n")
    line_index = 0
    while line_index < len(lines) and lines[line_index].startswith("#"):
        line_index += 1
    while line_index < len(lines) and not lines[line_index].strip():
        line_index += 1
    return "\n".join(lines[line_index:])


def _load_workflow_yaml(content: str) -> object:
    return yaml.load(content, Loader=_GitHubActionsLoader)


def _preserve_existing_triggers(existing_content: str, new_content: str) -> str:
    existing_data = _load_workflow_yaml(_extract_body(existing_content))
    new_data = _load_workflow_yaml(new_content)

    if not isinstance(existing_data, dict) or not isinstance(new_data, dict):
        raise ValueError("Workflow YAML must be a mapping to preserve trigger configuration.")

    if "on" not in existing_data:
        return new_content

    if new_data.get("on") == existing_data["on"]:
        return new_content

    new_data["on"] = existing_data["on"]

    return yaml.safe_dump(new_data, sort_keys=False)


def _resolve_target(entry: WorkflowEntry, installed_file: InstalledFile) -> str:
    if _is_workflow_target(installed_file.target) and entry.target:
        return f".github/workflows/{entry.target}"
    return installed_file.target


def _sync_workflow_file(
    cwd: Path,
    entry: WorkflowEntry,
    workflow_source: WorkflowSource,
    installed_file: InstalledFile,
    *,
    force: bool,
    is_update: bool,
    update_triggers: bool,
) -> _InstalledFileResult:
    target = _resolve_target(entry, installed_file)
    target_path = cwd / target
    existing_content = target_path.read_text(encoding="utf-8") if target_path.is_file() else None

    if existing_content is not None and not _is_managed(existing_content, entry.name) and not force:
        raise _WorkflowBlockedError("unmanaged file exists")

    workflow_body = installed_file.content.decode("utf-8")
    if existing_content is not None and is_update and not (entry.update_triggers or update_triggers):
        workflow_body = _preserve_existing_triggers(existing_content, workflow_body)

    normalized_body = _normalize_workflow_body(workflow_body)
    source_hash = _sha256(normalized_body)
    header = _build_header(
        entry.name,
        entry.version,
        f"{workflow_source.package_name}:{installed_file.source}",
        source_hash,
    )
    rendered = f"{header}\n\n{normalized_body}"

    changed = existing_content is None or existing_content.rstrip() != rendered.rstrip()
    if changed:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(rendered, encoding="utf-8")

    return _InstalledFileResult(
        changed=changed,
        lock_file=LockFileEntry(target=target, source_hash=source_hash),
    )


def _sync_config_file(
    cwd: Path,
    entry: WorkflowEntry,
    installed_file: InstalledFile,
    *,
    is_update: bool,
    previous_lock_file: LockFileEntry | None,
) -> _InstalledFileResult:
    target_path = cwd / installed_file.target
    source_hash = _sha256_bytes(installed_file.content)

    if not is_update:
        if target_path.exists():
            return _InstalledFileResult(changed=False, lock_file=None)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(installed_file.content)
        return _InstalledFileResult(
            changed=True,
            lock_file=LockFileEntry(target=installed_file.target, source_hash=source_hash, overwrite=False),
        )

    if not entry.update_config_files:
        if previous_lock_file is not None and target_path.exists():
            return _InstalledFileResult(changed=False, lock_file=previous_lock_file)
        return _InstalledFileResult(changed=False, lock_file=None)

    existing_content = target_path.read_bytes() if target_path.exists() else None
    changed = existing_content != installed_file.content
    if changed:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(installed_file.content)

    return _InstalledFileResult(
        changed=changed,
        lock_file=LockFileEntry(target=installed_file.target, source_hash=source_hash, overwrite=True),
    )


def _prune_workflow_files(cwd: Path, entry: LockEntry, *, force: bool) -> str | None:
    for file_entry in entry.files:
        if not _is_workflow_target(file_entry.target):
            continue

        target_path = cwd / file_entry.target
        if not target_path.is_file():
            continue

        content = target_path.read_text(encoding="utf-8")
        if not _is_managed(content, entry.name) and not force:
            return "unmanaged"

        body = _extract_body(content)
        if file_entry.source_hash and _sha256(_normalize_workflow_body(body)) != file_entry.source_hash and not force:
            return "modified"

        target_path.unlink()

    return None

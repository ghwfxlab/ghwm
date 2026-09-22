"""Install, update, and prune workflow files in the consumer repository."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ghwm.download import WorkflowSource, download_workflows
from ghwm.lock import LockEntry, Lockfile, LockFileEntry, read_lockfile, write_lockfile
from ghwm.managed_files import (
    WorkflowBlockedError,
    prune_workflow_files,
    resolve_target,
    sync_config_file,
    sync_workflow_file,
)
from ghwm.manifest import Manifest, WorkflowEntry
from ghwm.metadata import extract_workflow_metadata
from ghwm.paths import is_workflow_target
from ghwm.telemetry import is_public_repository, is_telemetry_disabled, track_installation


@dataclass
class InstallResult:
    installed: list[str]
    updated: list[str]
    pruned: list[str]
    skipped: list[tuple[str, str]]  # (name, reason)


def install_workflows(
    cwd: Path,
    manifest: Manifest,
    *,
    force: bool = False,
    prune: bool = True,
    local_path: Path | None = None,
    update_triggers: bool = False,
    update_envs: bool = False,
    no_telemetry: bool = False,
) -> InstallResult:
    """Full install: download, write, and prune stale workflows."""
    lockfile = read_lockfile(cwd)
    sources = download_workflows(manifest, local_path=local_path)
    workflow_sources_by_name = {workflow_source.name: workflow_source for workflow_source in sources}

    result = InstallResult(installed=[], updated=[], pruned=[], skipped=[])

    for entry in manifest.workflows:
        workflow_source = workflow_sources_by_name[entry.name]
        _install_one(
            cwd,
            entry,
            workflow_source,
            lockfile,
            result,
            force=force,
            update_triggers=update_triggers,
            update_envs=update_envs,
        )

    if prune:
        _prune_stale(cwd, manifest, lockfile, result, force=force)

    if not (no_telemetry or is_telemetry_disabled()):
        _emit_telemetry(manifest.source, manifest, result, workflow_sources_by_name=workflow_sources_by_name)

    write_lockfile(cwd, lockfile)
    return result


def update_workflows(
    cwd: Path,
    manifest: Manifest,
    *,
    force: bool = False,
    prune: bool = False,
    local_path: Path | None = None,
    update_triggers: bool = False,
    update_envs: bool = False,
    no_telemetry: bool = False,
) -> InstallResult:
    """Re-download and re-install all workflows, optionally pruning stale ones."""
    return install_workflows(
        cwd,
        manifest,
        force=force,
        prune=prune,
        local_path=local_path,
        update_triggers=update_triggers,
        update_envs=update_envs,
        no_telemetry=no_telemetry,
    )


def _emit_telemetry(
    source: str,
    manifest: Manifest,
    result: InstallResult,
    workflow_sources_by_name: dict[str, WorkflowSource] | None = None,
) -> None:
    """Emit telemetry events for installs and updates if the workflow source registry is public."""
    if is_telemetry_disabled():
        return
    try:
        entry_by_name = {entry.name: entry for entry in manifest.workflows}
        workflow_sources_map = workflow_sources_by_name or {}
        public_cache: dict[tuple[str, str], bool] = {}

        events = [(name, "install") for name in result.installed] + [(name, "updated") for name in result.updated]

        for name, event_type in events:
            entry = entry_by_name.get(name)
            workflow_source_str = (entry.source if entry and entry.source else None) or source
            try:
                owner, repo = workflow_source_str.split("/", 1)
            except (ValueError, AttributeError):
                continue

            if (owner, repo) not in public_cache:
                public_cache[(owner, repo)] = is_public_repository(owner, repo)

            if not public_cache[(owner, repo)]:
                continue

            version = entry.version if entry else None
            workflow_source = workflow_sources_map.get(name)
            metadata = (
                workflow_source.metadata
                if workflow_source and workflow_source.metadata is not None
                else extract_workflow_metadata(
                    source=workflow_source_str,
                    version=version,
                )
            )

            track_installation(
                source=workflow_source_str,
                workflow_name=name,
                version=version,
                event_type=event_type,
                metadata=metadata,
            )
    except Exception:
        # Telemetry failures must never break the install
        return


def _install_one(
    cwd: Path,
    entry: WorkflowEntry,
    workflow_source: WorkflowSource,
    lockfile: Lockfile,
    result: InstallResult,
    *,
    force: bool,
    update_triggers: bool,
    update_envs: bool,
) -> None:
    existing_lock = lockfile.find(entry.name)
    is_update = existing_lock is not None
    tracked_files: list[LockFileEntry] = []
    changed = False

    sorted_files = sorted(
        workflow_source.files,
        key=lambda installed_file: not is_workflow_target(installed_file.target),
    )

    try:
        for installed_file in sorted_files:
            target = resolve_target(cwd, entry, installed_file)
            previous_lock_file = existing_lock.find_file(target) if existing_lock is not None else None

            if is_workflow_target(installed_file.target):
                file_result = sync_workflow_file(
                    cwd,
                    entry,
                    workflow_source,
                    installed_file,
                    force=force,
                    is_update=is_update,
                    update_triggers=update_triggers,
                    update_envs=update_envs,
                )
            else:
                file_result = sync_config_file(
                    cwd,
                    entry,
                    installed_file,
                    is_update=is_update,
                    previous_lock_file=previous_lock_file,
                )

            changed = changed or file_result.changed
            if file_result.lock_file is not None:
                tracked_files.append(file_result.lock_file)
    except WorkflowBlockedError as exc:
        result.skipped.append((entry.name, str(exc)))
        return

    lockfile.upsert(
        LockEntry(
            name=entry.name,
            version=entry.version,
            source=workflow_source.package_name,
            files=tracked_files,
        )
    )

    if changed:
        if is_update:
            result.updated.append(entry.name)
        else:
            result.installed.append(entry.name)
    else:
        result.skipped.append((entry.name, "already up to date"))


def _prune_stale(
    cwd: Path,
    manifest: Manifest,
    lockfile: Lockfile,
    result: InstallResult,
    *,
    force: bool,
) -> None:
    manifest_workflow_names = {workflow_entry.name for workflow_entry in manifest.workflows}
    stale_entries = [lock_entry for lock_entry in lockfile.packages if lock_entry.name not in manifest_workflow_names]

    for entry in stale_entries:
        skip_reason = prune_workflow_files(cwd, entry, force=force)
        if skip_reason is not None:
            result.skipped.append((entry.name, skip_reason))
            continue

        lockfile.remove(entry.name)
        result.pruned.append(entry.name)

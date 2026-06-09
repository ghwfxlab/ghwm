"""Install, update, and prune workflow files in the consumer repository."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ghwm.download import WorkflowSource, download_workflows
from ghwm.lock import LockEntry, Lockfile, LockFileEntry, read_lockfile, write_lockfile
from ghwm.managed_files import (
    _is_workflow_target,
    _prune_workflow_files,
    _resolve_target,
    _sync_config_file,
    _sync_workflow_file,
    _WorkflowBlockedError,
)
from ghwm.manifest import Manifest, WorkflowEntry


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
) -> InstallResult:
    """Full install: download, write, and prune stale workflows."""
    lockfile = read_lockfile(cwd)
    workflow_refs = {workflow_entry.name: workflow_entry.resolved_ref for workflow_entry in manifest.workflows}
    workflow_names = [workflow_entry.name for workflow_entry in manifest.workflows]

    sources = download_workflows(manifest.source, workflow_names, workflow_refs, local_path=local_path)
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
        )

    if prune:
        _prune_stale(cwd, manifest, lockfile, result, force=force)

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
) -> InstallResult:
    """Re-download and re-install all workflows, optionally pruning stale ones."""
    return install_workflows(
        cwd,
        manifest,
        force=force,
        prune=prune,
        local_path=local_path,
        update_triggers=update_triggers,
    )


def _install_one(
    cwd: Path,
    entry: WorkflowEntry,
    workflow_source: WorkflowSource,
    lockfile: Lockfile,
    result: InstallResult,
    *,
    force: bool,
    update_triggers: bool,
) -> None:
    existing_lock = lockfile.find(entry.name)
    is_update = existing_lock is not None
    tracked_files: list[LockFileEntry] = []
    changed = False

    sorted_files = sorted(
        workflow_source.files,
        key=lambda installed_file: not _is_workflow_target(installed_file.target),
    )

    try:
        for installed_file in sorted_files:
            target = _resolve_target(cwd, entry, installed_file)
            previous_lock_file = existing_lock.find_file(target) if existing_lock is not None else None

            if _is_workflow_target(installed_file.target):
                file_result = _sync_workflow_file(
                    cwd,
                    entry,
                    workflow_source,
                    installed_file,
                    force=force,
                    is_update=is_update,
                    update_triggers=update_triggers,
                )
            else:
                file_result = _sync_config_file(
                    cwd,
                    entry,
                    installed_file,
                    is_update=is_update,
                    previous_lock_file=previous_lock_file,
                )

            changed = changed or file_result.changed
            if file_result.lock_file is not None:
                tracked_files.append(file_result.lock_file)
    except _WorkflowBlockedError as exc:
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
        skip_reason = _prune_workflow_files(cwd, entry, force=force)
        if skip_reason is not None:
            result.skipped.append((entry.name, skip_reason))
            continue

        lockfile.remove(entry.name)
        result.pruned.append(entry.name)

"""Manage installed workflow and config files."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ghwm.download import WorkflowSource
from ghwm.download_npm import InstalledFile
from ghwm.lock import LockEntry, LockFileEntry
from ghwm.manifest import WorkflowEntry
from ghwm.paths import is_workflow_target, safe_resolve_path


class WorkflowBlockedError(Exception):
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

_TOP_LEVEL_MAPPING_KEY = re.compile(
    r"""^(?P<key>[A-Za-z0-9_-]+|"[^"]+"|'[^']+')\s*:(?:[ \t]|$)""",
    re.MULTILINE,
)


@dataclass
class InstalledFileResult:
    changed: bool
    lock_file: LockFileEntry | None
    notices: list[str] = field(default_factory=list)


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


def extract_body(content: str) -> str:
    """Strip the generated header, return the body."""
    lines = content.split("\n")
    line_index = 0
    while line_index < len(lines) and lines[line_index].startswith("#"):
        line_index += 1
    while line_index < len(lines) and not lines[line_index].strip():
        line_index += 1
    return "\n".join(lines[line_index:])


def load_workflow_yaml(content: str) -> object:
    return yaml.load(content, Loader=_GitHubActionsLoader)  # noqa: S506


def _find_top_level_section(content: str, key: str) -> tuple[int, int] | None:
    matches = list(_TOP_LEVEL_MAPPING_KEY.finditer(content))
    for index, match in enumerate(matches):
        raw_key = match.group("key")
        if raw_key not in {key, f'"{key}"', f"'{key}'"}:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        return match.start(), end
    return None


def _preserve_existing_top_level_value(
    existing_content: str,
    new_content: str,
    *,
    key: str,
    description: str,
) -> str:
    existing_data = load_workflow_yaml(extract_body(existing_content))
    new_data = load_workflow_yaml(new_content)

    if not isinstance(existing_data, dict) or not isinstance(new_data, dict):
        raise ValueError(f"Workflow YAML must be a mapping to preserve {description} configuration.")

    if key not in existing_data:
        return new_content

    if new_data.get(key) == existing_data[key]:
        return new_content

    existing_body = extract_body(existing_content)
    existing_section = _find_top_level_section(existing_body, key)
    if existing_section is None:
        raise ValueError(f"Could not find the existing {description} section in the workflow YAML.")

    new_section = _find_top_level_section(new_content, key)
    preserved_section = existing_body[existing_section[0] : existing_section[1]]

    if new_section is None:
        return f"{new_content.rstrip()}\n{preserved_section}"

    return f"{new_content[: new_section[0]]}{preserved_section}{new_content[new_section[1] :]}"


def _preserve_existing_triggers(existing_content: str, new_content: str) -> str:
    return _preserve_existing_top_level_value(
        existing_content,
        new_content,
        key="on",
        description="trigger",
    )


def _preserve_existing_envs(existing_content: str, new_content: str) -> str:
    return _preserve_existing_top_level_value(
        existing_content,
        new_content,
        key="env",
        description="env",
    )


def _first_child_indent(content: str, start: int, end: int) -> int | None:
    for line in content[start:end].split("\n"):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return len(line) - len(line.lstrip(" "))
    return None


def _trim_trailing_blank_lines(content: str, start: int, end: int) -> int:
    """Move ``end`` back over trailing blank and comment-only lines, which belong to the next key."""
    while end > start:
        line_start = content.rfind("\n", start, end - 1) + 1
        line_start = max(line_start, start)
        stripped = content[line_start:end].strip()
        if stripped and not stripped.startswith("#"):
            break
        end = line_start
    return end


def _find_child_section(content: str, parent: tuple[int, int], key: str) -> tuple[int, int] | None:
    """Locate ``key`` among the direct children of the mapping section ``parent``."""
    parent_start, parent_end = parent
    header_end = content.find("\n", parent_start, parent_end)
    if header_end == -1:
        return None
    children_start = header_end + 1
    indent = _first_child_indent(content, children_start, parent_end)
    if not indent:
        return None

    child_key_pattern = re.compile(
        rf"""^ {{{indent}}}(?P<key>[A-Za-z0-9_-]+|"[^"]+"|'[^']+')\s*:(?:[ \t]|$)""",
        re.MULTILINE,
    )
    child_keys = list(child_key_pattern.finditer(content, children_start, parent_end))
    for index, match in enumerate(child_keys):
        if match.group("key") not in {key, f'"{key}"', f"'{key}'"}:
            continue
        end = child_keys[index + 1].start() if index + 1 < len(child_keys) else parent_end
        return match.start(), _trim_trailing_blank_lines(content, match.start(), end)
    return None


def _locate_job_runs_on(content: str, job_id: str) -> tuple[int, int] | None:
    jobs_section = _find_top_level_section(content, "jobs")
    if jobs_section is None:
        return None
    job_section = _find_child_section(content, jobs_section, job_id)
    if job_section is None:
        return None
    return _find_child_section(content, job_section, "runs-on")


def _leading_spaces(content: str, line_start: int) -> int:
    line_end = content.find("\n", line_start)
    line = content[line_start:] if line_end == -1 else content[line_start:line_end]
    return len(line) - len(line.lstrip(" "))


def _shift_indent(text: str, delta: int) -> str:
    if delta == 0:
        return text
    lines = text.split("\n")
    if delta > 0:
        return "\n".join(f"{' ' * delta}{line}" if line.strip() else line for line in lines)
    remove = -delta
    return "\n".join(line[min(remove, len(line) - len(line.lstrip(" "))) :] for line in lines)


def _preserve_existing_runs_on(existing_content: str, new_content: str, *, name: str) -> tuple[str, list[str]]:
    """Keep each job's existing ``runs-on`` text, matched by job id.

    Returns the merged content plus notices for preserved jobs that no longer exist in the package.
    """
    existing_body = extract_body(existing_content)
    existing_data = load_workflow_yaml(existing_body)
    new_data = load_workflow_yaml(new_content)

    if not isinstance(existing_data, dict) or not isinstance(new_data, dict):
        raise ValueError("Workflow YAML must be a mapping to preserve runs-on configuration.")

    existing_jobs = existing_data.get("jobs")
    new_jobs = new_data.get("jobs")
    if not isinstance(existing_jobs, dict) or not isinstance(new_jobs, dict):
        return new_content, []

    merged = new_content
    notices: list[str] = []
    for job_id, existing_job in existing_jobs.items():
        if not isinstance(existing_job, dict) or "runs-on" not in existing_job:
            continue
        if job_id not in new_jobs:
            notices.append(f"{name}: job '{job_id}' no longer exists upstream; its local runs-on was not kept")
            continue
        new_job = new_jobs[job_id]
        if not isinstance(new_job, dict) or "runs-on" not in new_job:
            continue
        if new_job["runs-on"] == existing_job["runs-on"]:
            continue

        existing_span = _locate_job_runs_on(existing_body, str(job_id))
        new_span = _locate_job_runs_on(merged, str(job_id))
        if existing_span is None or new_span is None:
            raise ValueError(f"Could not find the runs-on section of job '{job_id}' in the workflow YAML.")

        preserved = existing_body[existing_span[0] : existing_span[1]]
        indent_delta = _leading_spaces(merged, new_span[0]) - _leading_spaces(existing_body, existing_span[0])
        preserved = _shift_indent(preserved, indent_delta)
        if not preserved.endswith("\n"):
            preserved = f"{preserved}\n"
        merged = f"{merged[: new_span[0]]}{preserved}{merged[new_span[1] :]}"

    return merged, notices


def resolve_target(cwd: Path, entry: WorkflowEntry, installed_file: InstalledFile) -> str:
    if is_workflow_target(installed_file.target) and entry.target:
        raw_target = f".github/workflows/{entry.target}"
    else:
        raw_target = installed_file.target
    safe_path = safe_resolve_path(cwd, raw_target)
    return str(safe_path.relative_to(cwd))


def sync_workflow_file(
    cwd: Path,
    entry: WorkflowEntry,
    workflow_source: WorkflowSource,
    installed_file: InstalledFile,
    *,
    force: bool,
    is_update: bool,
    update_triggers: bool,
    update_envs: bool,
    update_runs_on: bool,
) -> InstalledFileResult:
    target = resolve_target(cwd, entry, installed_file)
    target_path = cwd / target
    existing_content = target_path.read_text(encoding="utf-8") if target_path.is_file() else None
    notices: list[str] = []

    if existing_content is not None and not _is_managed(existing_content, entry.name) and not force:
        raise WorkflowBlockedError("unmanaged file exists")

    workflow_body = installed_file.content.decode("utf-8")
    if existing_content is not None and is_update:
        if not (entry.update_triggers or update_triggers):
            workflow_body = _preserve_existing_triggers(existing_content, workflow_body)
        if not (entry.update_envs or update_envs):
            workflow_body = _preserve_existing_envs(existing_content, workflow_body)
        if not (entry.update_runs_on or update_runs_on):
            workflow_body, notices = _preserve_existing_runs_on(existing_content, workflow_body, name=entry.name)

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

    return InstalledFileResult(
        changed=changed,
        lock_file=LockFileEntry(target=target, source_hash=source_hash),
        notices=notices,
    )


def sync_config_file(
    cwd: Path,
    entry: WorkflowEntry,
    installed_file: InstalledFile,
    *,
    is_update: bool,
    previous_lock_file: LockFileEntry | None,
) -> InstalledFileResult:
    target = resolve_target(cwd, entry, installed_file)
    target_path = cwd / target
    source_hash = _sha256_bytes(installed_file.content)

    if not is_update:
        if target_path.exists():
            return InstalledFileResult(changed=False, lock_file=None)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(installed_file.content)
        return InstalledFileResult(
            changed=True,
            lock_file=LockFileEntry(target=target, source_hash=source_hash, overwrite=False),
        )

    if not entry.update_config_files:
        if previous_lock_file is not None and target_path.exists():
            return InstalledFileResult(changed=False, lock_file=previous_lock_file)
        return InstalledFileResult(changed=False, lock_file=None)

    existing_content = target_path.read_bytes() if target_path.exists() else None
    changed = existing_content != installed_file.content
    if changed:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(installed_file.content)

    return InstalledFileResult(
        changed=changed,
        lock_file=LockFileEntry(target=target, source_hash=source_hash, overwrite=True),
    )


def prune_workflow_files(cwd: Path, entry: LockEntry, *, force: bool) -> str | None:
    for file_entry in entry.files:
        if not is_workflow_target(file_entry.target):
            continue

        target_path = safe_resolve_path(cwd, file_entry.target)
        if not target_path.is_file():
            continue

        content = target_path.read_text(encoding="utf-8")
        if not _is_managed(content, entry.name) and not force:
            return "unmanaged"

        body = extract_body(content)
        if file_entry.source_hash and _sha256(_normalize_workflow_body(body)) != file_entry.source_hash and not force:
            return "modified"

        target_path.unlink()

    return None

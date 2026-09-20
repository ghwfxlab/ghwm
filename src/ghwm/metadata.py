"""Metadata extraction for workflow packages."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import yaml

from ghwm.paths import is_workflow_target

if TYPE_CHECKING:
    from ghwm.download_npm import InstalledFile


def parse_commented_frontmatter(content: str) -> dict[str, Any]:
    """Parse commented YAML frontmatter delimited by ``# ---`` or top-of-file comments."""
    if not content:
        return {}

    stripped = content.lstrip()
    if not stripped.startswith("#"):
        return {}

    comment_lines: list[str] = []
    in_delimited_block = False
    has_delimiter = False

    for line in content.splitlines():
        trimmed = line.strip()
        if trimmed == "# ---":
            if not in_delimited_block:
                in_delimited_block = True
                has_delimiter = True
                comment_lines = []
                continue
            break

        if in_delimited_block:
            if not trimmed.startswith("#") and trimmed != "":
                break
            comment_lines.append(line.removeprefix("# ").removeprefix("#"))
            continue

        if not has_delimiter:
            if trimmed.startswith("#"):
                comment_lines.append(line.removeprefix("# ").removeprefix("#"))
            elif trimmed == "":
                continue
            else:
                break

    if not comment_lines:
        return {}

    try:
        parsed = yaml.safe_load("\n".join(comment_lines))
        return parsed if isinstance(parsed, dict) else {}
    except (yaml.YAMLError, AttributeError):
        return {}


def parse_tags(raw_tags: Any) -> list[str]:
    """Parse and normalize workflow category tags to a list of strings."""
    if isinstance(raw_tags, list):
        parsed = [str(item).strip() for item in raw_tags if str(item).strip()]
    elif isinstance(raw_tags, str):
        trimmed = raw_tags.strip()
        if trimmed.startswith("[") and trimmed.endswith("]"):
            trimmed = trimmed[1:-1]
        parsed = [item.strip().strip("'\"") for item in trimmed.split(",") if item.strip().strip("'\"")]
    else:
        return []

    unique_tags = list(dict.fromkeys(parsed))
    return [tag[:64] for tag in unique_tags[:20]]


def find_workflow_file_content(files: list[InstalledFile]) -> str | None:
    """Find and decode the primary workflow file content from installed files."""
    for installed_file in files:
        if is_workflow_target(installed_file.target):
            return installed_file.content.decode("utf-8", errors="replace")
    return None


def _trim_optional_str(value: Any, max_len: int) -> str | None:
    """Trim string representation of value to max_len; return None if falsy or empty."""
    if value is None:
        return None
    trimmed = str(value).strip()
    return trimmed[:max_len] if trimmed else None


def _first_non_none(*values: Any) -> Any:
    """Return the first non-None value, or None if all values are None."""
    for val in values:
        if val is not None:
            return val
    return None


def extract_workflow_metadata(
    source: str,
    *,
    version: str | None = None,
    workflow_yml_content: str | None = None,
    workflow_file_content: str | None = None,
    package_json_content: str | None = None,
    manifest_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract structured metadata for a workflow package.

    Resolution precedence for fields:
    1. Commented YAML frontmatter in ``workflow.yml`` (or workflow file)
    2. Parsed manifest keys in ``workflow.yml``
    3. ``package.json`` fields (description, version)
    4. Sane defaults based on ``source`` and ``version``
    """
    frontmatter: dict[str, Any] = {}

    if workflow_yml_content:
        frontmatter = parse_commented_frontmatter(workflow_yml_content)

    if not frontmatter and workflow_file_content:
        frontmatter = parse_commented_frontmatter(workflow_file_content)

    # Allow top-level keys in parsed workflow.yml if not in frontmatter
    manifest_keys = manifest_data or {}

    pkg_data: dict[str, Any] = {}
    if package_json_content:
        try:
            parsed_pkg = json.loads(package_json_content)
            if isinstance(parsed_pkg, dict):
                pkg_data = parsed_pkg
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Malformed or unreadable package.json is ignored; fallback to frontmatter/manifest
            pkg_data = {}

    default_owner = source.split("/", 1)[0] if "/" in source else None

    raw_title = _first_non_none(frontmatter.get("title"), manifest_keys.get("title"))
    title = _trim_optional_str(raw_title, 128)

    raw_description = _first_non_none(
        frontmatter.get("description"), manifest_keys.get("description"), pkg_data.get("description")
    )
    description = _trim_optional_str(raw_description, 2048)

    raw_tags = _first_non_none(frontmatter.get("tags"), manifest_keys.get("tags"))
    tags = parse_tags(raw_tags)

    raw_icon = _first_non_none(frontmatter.get("icon"), manifest_keys.get("icon"))
    icon = _trim_optional_str(raw_icon, 64)

    raw_owner = _first_non_none(frontmatter.get("owner"), manifest_keys.get("owner"), default_owner)
    owner = _trim_optional_str(raw_owner, 128)

    raw_version = _first_non_none(
        version, frontmatter.get("version"), manifest_keys.get("version"), pkg_data.get("version")
    )
    resolved_version = _trim_optional_str(raw_version, 64)

    resolved_source = _trim_optional_str(source, 512) or source

    metadata: dict[str, Any] = {
        "title": title,
        "description": description,
        "tags": tags,
        "icon": icon,
        "version": resolved_version,
        "owner": owner,
        "source": resolved_source,
    }

    raw_created_at = _first_non_none(
        frontmatter.get("created_at"),
        frontmatter.get("createdAt"),
        manifest_keys.get("created_at"),
        manifest_keys.get("createdAt"),
    )
    created_at = _trim_optional_str(raw_created_at, 64)
    if created_at is not None:
        metadata["created_at"] = created_at

    return metadata

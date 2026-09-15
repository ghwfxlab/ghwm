"""Metadata extraction for workflow packages."""

from __future__ import annotations

import json
from typing import Any

import yaml


def parse_commented_frontmatter(content: str) -> dict[str, Any]:
    """Parse commented YAML frontmatter delimited by ``# ---`` or top-of-file comments."""
    if not content:
        return {}

    lines = content.splitlines()
    comment_lines: list[str] = []
    in_delimited_block = False

    for line in lines:
        trimmed = line.strip()
        if trimmed == "# ---":
            if not in_delimited_block:
                in_delimited_block = True
                continue
            break

        if in_delimited_block:
            comment_lines.append(line.removeprefix("# ").removeprefix("#"))
            continue

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

    return [tag[:64] for tag in parsed[:20]]


def _trim_optional_str(value: Any, max_len: int) -> str | None:
    if value is None:
        return None
    trimmed = str(value).strip()
    return trimmed[:max_len] if trimmed else None


def extract_workflow_metadata(
    workflow_name: str,
    source: str,
    *,
    version: str | None = None,
    workflow_yml_content: str | None = None,
    workflow_file_content: str | None = None,
    package_json_content: str | None = None,
    manifest_data: dict[str, Any] | None = None,
    repo_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract structured metadata for a workflow from package files and defaults."""
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

    raw_title = frontmatter.get("title") or manifest_keys.get("title")
    title = _trim_optional_str(raw_title, 128)

    raw_description = (
        frontmatter.get("description")
        or manifest_keys.get("description")
        or pkg_data.get("description")
        or (repo_info.get("description") if repo_info else None)
    )
    description = _trim_optional_str(raw_description, 2048)

    raw_tags = frontmatter.get("tags") or manifest_keys.get("tags") or (repo_info.get("topics") if repo_info else None)
    tags = parse_tags(raw_tags)

    raw_icon = frontmatter.get("icon") or manifest_keys.get("icon")
    icon = _trim_optional_str(raw_icon, 64)

    raw_owner = frontmatter.get("owner") or manifest_keys.get("owner") or default_owner
    owner = _trim_optional_str(raw_owner, 128)

    raw_version = version or frontmatter.get("version") or manifest_keys.get("version") or pkg_data.get("version")
    clean_version = _trim_optional_str(raw_version, 64)

    clean_source = (
        _trim_optional_str(
            frontmatter.get("source") or frontmatter.get("source_url") or source,
            512,
        )
        or source
    )

    metadata: dict[str, Any] = {
        "title": title,
        "description": description,
        "tags": tags,
        "icon": icon,
        "version": clean_version,
        "owner": owner,
        "source": clean_source,
    }

    raw_created_at = frontmatter.get("created_at") or frontmatter.get("createdAt")
    created_at = _trim_optional_str(raw_created_at, 64)
    if created_at is not None:
        metadata["created_at"] = created_at

    return metadata

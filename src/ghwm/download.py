"""Download workflow packages from GitHub Packages or a local registry checkout."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ghwm.download_npm import (
    InstalledFile,
    build_installed_files,
    download_npm_tarball,
    extract_npm_package,
    extract_tarball_metadata,
    parse_workflow_manifest_data,
    read_workflow_manifest,
)
from ghwm.manifest import Manifest
from ghwm.metadata import extract_workflow_metadata, find_workflow_file_content
from ghwm.package_names import scoped_package_name
from ghwm.paths import safe_resolve_path


@dataclass(frozen=True)
class WorkflowSource:
    """Downloaded workflow package content."""

    name: str
    package_name: str
    files: list[InstalledFile]
    metadata: dict[str, Any] | None = None


def gh_cli_available() -> bool:
    return shutil.which("gh") is not None


def github_token() -> str | None:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        return token

    if gh_cli_available():
        gh_bin = shutil.which("gh")
        if gh_bin:
            result = subprocess.run(  # noqa: S603
                [gh_bin, "auth", "token"],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                token = result.stdout.strip()
                if token:
                    return token

    return None


def download_workflows(
    manifest: Manifest,
    *,
    local_path: Path | None = None,
) -> list[WorkflowSource]:
    """Download one or more workflow packages."""
    if local_path:
        return read_local(local_path, manifest)

    token = github_token()
    results: list[WorkflowSource] = []

    for entry in manifest.workflows:
        version = entry.resolved_ref
        if not version or version == "main":
            raise ValueError(f"Workflow '{entry.name}' must specify a version in ghwm.yml.")

        entry_source = entry.source or manifest.source
        owner, _ = entry_source.split("/", 1)

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_dir = Path(tmpdir)
            tarball_path = download_npm_tarball(owner, entry.name, version, temp_dir, token)
            manifest_data = read_workflow_manifest(tarball_path)
            files = extract_npm_package(tarball_path, manifest_data)
            metadata = extract_tarball_metadata(
                tarball_path,
                source=entry_source,
                version=version,
                manifest_data=manifest_data,
                files=files,
            )
            results.append(
                WorkflowSource(
                    name=entry.name,
                    package_name=scoped_package_name(owner, entry.name),
                    files=files,
                    metadata=metadata,
                )
            )

    return results


def read_local(local_path: Path, manifest: Manifest) -> list[WorkflowSource]:
    """Read workflow packages from a local checkout."""
    return read_from_tree(local_path, manifest)


def _extract_local_workflow_metadata(
    *,
    workflow_dir: Path,
    source: str,
    version: str | None,
    manifest_text: str,
    manifest_data: dict[str, Any],
    files: list[InstalledFile],
) -> dict[str, Any]:
    """Extract metadata for a local workflow package from its directory and files."""
    pkg_json_path = workflow_dir / "package.json"
    pkg_json_content = pkg_json_path.read_text(encoding="utf-8") if pkg_json_path.is_file() else None

    workflow_file_content = find_workflow_file_content(files)

    return extract_workflow_metadata(
        source=source,
        version=version,
        workflow_yml_content=manifest_text,
        workflow_file_content=workflow_file_content,
        package_json_content=pkg_json_content,
        manifest_data=manifest_data,
    )


def read_from_tree(repo_root: Path, manifest: Manifest) -> list[WorkflowSource]:
    """Read workflow packages from a local repository tree."""
    workflows_dir = repo_root / "workflows"
    results: list[WorkflowSource] = []

    for entry in manifest.workflows:
        entry_source = entry.source or manifest.source
        owner, _ = entry_source.split("/", 1)
        name = entry.name
        workflow_dir = workflows_dir / name
        if not workflow_dir.is_dir():
            raise FileNotFoundError(f"Workflow directory not found: workflows/{name}")

        manifest_path = workflow_dir / "workflow.yml"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Workflow package manifest not found: workflows/{name}/workflow.yml")

        manifest_text = manifest_path.read_text(encoding="utf-8")
        manifest_data = parse_workflow_manifest_data(yaml.safe_load(manifest_text))

        def read_file(file_source: str, workflow_dir: Path = workflow_dir, name: str = name) -> bytes:
            return _read_local_package_file(workflow_dir, name, file_source)

        files = build_installed_files(manifest_data, read_file)

        metadata = _extract_local_workflow_metadata(
            workflow_dir=workflow_dir,
            source=entry_source,
            version=entry.version,
            manifest_text=manifest_text,
            manifest_data=manifest_data,
            files=files,
        )

        results.append(
            WorkflowSource(
                name=name,
                package_name=scoped_package_name(owner, name),
                files=files,
                metadata=metadata,
            )
        )

    return results


def _read_local_package_file(workflow_dir: Path, workflow_name: str, file_source: str) -> bytes:
    source_path = safe_resolve_path(workflow_dir, file_source)
    if not source_path.is_file():
        raise FileNotFoundError(f"Workflow package file not found: workflows/{workflow_name}/{file_source}")
    return source_path.read_bytes()

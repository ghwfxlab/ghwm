"""Download workflow packages from GitHub Packages or a local marketplace checkout."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from ghwm.download_npm import (
    InstalledFile,
    build_installed_files,
    download_npm_tarball,
    extract_npm_package,
    parse_workflow_manifest_data,
    read_workflow_manifest,
)
from ghwm.package_names import scoped_package_name


@dataclass(frozen=True)
class WorkflowSource:
    """Downloaded workflow package content."""

    name: str
    package_name: str
    files: list[InstalledFile]


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
    source: str,
    workflow_names: list[str],
    workflow_refs: dict[str, str],
    *,
    local_path: Path | None = None,
) -> list[WorkflowSource]:
    """Download one or more workflow packages."""
    if local_path:
        return read_local(local_path, source, workflow_names)

    owner, _ = source.split("/", 1)
    token = github_token()
    results: list[WorkflowSource] = []

    for name in workflow_names:
        version = workflow_refs.get(name)
        if not version or version == "main":
            raise ValueError(f"Workflow '{name}' must specify a version in ghwm.yml.")

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_dir = Path(tmpdir)
            tarball_path = download_npm_tarball(owner, name, version, temp_dir, token)
            manifest_data = read_workflow_manifest(tarball_path)
            results.append(
                WorkflowSource(
                    name=name,
                    package_name=scoped_package_name(owner, name),
                    files=extract_npm_package(tarball_path, manifest_data),
                )
            )

    return results


def read_local(local_path: Path, source: str, workflow_names: list[str]) -> list[WorkflowSource]:
    """Read workflow packages from a local checkout."""
    return read_from_tree(local_path, source, workflow_names)


def read_from_tree(repo_root: Path, source: str, workflow_names: list[str]) -> list[WorkflowSource]:
    """Read workflow packages from a local repository tree."""
    owner, _ = source.split("/", 1)
    workflows_dir = repo_root / "workflows"
    results: list[WorkflowSource] = []

    for name in workflow_names:
        workflow_dir = workflows_dir / name
        if not workflow_dir.is_dir():
            raise FileNotFoundError(f"Workflow directory not found: workflows/{name}")

        manifest_path = workflow_dir / "workflow.yml"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Workflow package manifest not found: workflows/{name}/workflow.yml")

        manifest_data = parse_workflow_manifest_data(yaml.safe_load(manifest_path.read_text(encoding="utf-8")))

        def read_file(file_source: str, workflow_dir: Path = workflow_dir, name: str = name) -> bytes:
            return _read_local_package_file(workflow_dir, name, file_source)

        files = build_installed_files(manifest_data, read_file)

        results.append(
            WorkflowSource(
                name=name,
                package_name=scoped_package_name(owner, name),
                files=files,
            )
        )

    return results


def _read_local_package_file(workflow_dir: Path, workflow_name: str, file_source: str) -> bytes:
    source_path = workflow_dir / file_source
    if not source_path.is_file():
        raise FileNotFoundError(f"Workflow package file not found: workflows/{workflow_name}/{file_source}")
    return source_path.read_bytes()

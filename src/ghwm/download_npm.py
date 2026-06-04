"""Download workflow packages from GitHub Packages."""

from __future__ import annotations

import json
import shutil
import tarfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

import yaml

from ghwm.package_names import scoped_package_name

REGISTRY_URL = "https://npm.pkg.github.com"


@dataclass(frozen=True)
class InstalledFile:
    """A packaged file that should be installed into the consumer repository."""

    source: str
    content: bytes
    target: str


def npm_package_metadata_url(org: str, name: str) -> str:
    """Return the GitHub Packages metadata URL for a workflow package."""
    return f"{REGISTRY_URL}/{quote(scoped_package_name(org, name), safe='@')}"


def _github_packages_headers(token: str | None, *, accept: str) -> dict[str, str]:
    headers = {"Accept": accept, "User-Agent": "ghwm"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _github_packages_auth_error() -> RuntimeError:
    return RuntimeError(
        "GitHub Packages access requires a token with read:packages. "
        "Set GH_TOKEN/GITHUB_TOKEN or run `gh auth refresh -s read:packages`."
    )


def npm_tarball_url(org: str, name: str, version: str, token: str | None) -> str:
    """Return the resolved GitHub Packages tarball URL for a workflow package version."""
    package_name = scoped_package_name(org, name)
    request = Request(
        npm_package_metadata_url(org, name),
        headers=_github_packages_headers(token, accept="application/vnd.npm.install-v1+json"),
    )

    try:
        with urlopen(request) as metadata_response:
            metadata = json.load(metadata_response)
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise _github_packages_auth_error() from exc
        if exc.code == 404:
            raise FileNotFoundError(f"Workflow package not found in GitHub Packages: {package_name}") from exc
        raise

    versions = metadata.get("versions")
    if not isinstance(versions, dict):
        raise RuntimeError(f"Unexpected npm metadata response for {package_name}: missing 'versions' map.")

    package_version = versions.get(version)
    if not isinstance(package_version, dict):
        raise FileNotFoundError(f"Workflow package version not found in GitHub Packages: {package_name}@{version}")

    dist = package_version.get("dist")
    tarball_url = dist.get("tarball") if isinstance(dist, dict) else None
    if not isinstance(tarball_url, str) or not tarball_url:
        raise RuntimeError(f"Unexpected npm metadata response for {package_name}@{version}: missing dist.tarball.")

    return tarball_url


def download_npm_tarball(org: str, name: str, version: str, dest: Path, token: str | None) -> Path:
    """Download an npm package tarball from GitHub Packages."""
    tarball_url = npm_tarball_url(org, name, version, token)
    request = Request(
        tarball_url,
        headers=_github_packages_headers(token, accept="application/octet-stream"),
    )
    archive_path = dest / "package.tgz"

    try:
        with urlopen(request) as archive_response, archive_path.open("wb") as archive_file:
            shutil.copyfileobj(archive_response, archive_file)
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise _github_packages_auth_error() from exc
        if exc.code == 404:
            raise FileNotFoundError(
                f"Workflow package tarball not found in GitHub Packages: {scoped_package_name(org, name)}@{version}"
            ) from exc
        raise

    return archive_path


def parse_workflow_manifest_data(manifest_data: Any) -> dict[str, Any]:
    """Validate a parsed ``workflow.yml`` payload."""
    if not isinstance(manifest_data, dict):
        raise ValueError("workflow.yml must be a YAML mapping.")
    return manifest_data


def build_installed_files(manifest_data: Any, read_source: Callable[[str], bytes]) -> list[InstalledFile]:
    """Build installed files from a manifest and a file reader callback."""
    return [
        InstalledFile(source=source, content=read_source(source), target=target)
        for source, target in manifest_files(manifest_data)
    ]


def _read_tar_member(tar: tarfile.TarFile, member_name: str) -> bytes:
    try:
        source_member = tar.getmember(member_name)
    except KeyError as exc:
        raise FileNotFoundError(f"Package file not found: {member_name}") from exc

    source_file = tar.extractfile(source_member)
    if source_file is None:
        raise FileNotFoundError(f"Package file not found: {member_name}")

    return source_file.read()


def read_workflow_manifest(tarball_path: Path) -> dict[str, Any]:
    """Read ``package/workflow.yml`` from a package tarball."""
    with tarfile.open(tarball_path, "r:gz") as tar:
        manifest_data = yaml.safe_load(_read_tar_member(tar, "package/workflow.yml").decode("utf-8"))

    return parse_workflow_manifest_data(manifest_data)


def manifest_files(manifest_data: Any) -> list[tuple[str, str]]:
    """Return ``(source, target)`` pairs from a parsed workflow manifest."""
    if not isinstance(manifest_data, dict):
        raise ValueError("workflow.yml must be a YAML mapping.")

    raw_files = manifest_data.get("files")
    if not isinstance(raw_files, list):
        raise ValueError("workflow.yml must contain a 'files' list.")

    files: list[tuple[str, str]] = []
    for index, raw_file in enumerate(raw_files):
        if not isinstance(raw_file, dict):
            raise ValueError(f"workflow.yml files[{index}] must be a mapping.")
        source = raw_file.get("source")
        target = raw_file.get("target")
        if not isinstance(source, str) or not source:
            raise ValueError(f"workflow.yml files[{index}] must define a non-empty source.")
        if not isinstance(target, str) or not target:
            raise ValueError(f"workflow.yml files[{index}] must define a non-empty target.")
        files.append((source, target))
    return files


def extract_npm_package(tarball_path: Path, manifest_data: dict[str, Any]) -> list[InstalledFile]:
    """Extract packaged files listed in ``workflow.yml``."""
    with tarfile.open(tarball_path, "r:gz") as tar:
        return build_installed_files(
            manifest_data,
            lambda source: _read_tar_member(tar, f"package/{source}"),
        )

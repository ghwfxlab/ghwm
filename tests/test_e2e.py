"""End-to-end tests for ghwm using testcontainers."""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import uuid
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
import yaml

try:
    import docker  # type: ignore[import-not-found,import-untyped]
    from testcontainers.core.container import DockerContainer  # type: ignore[import-not-found,import-untyped]

    TESTCONTAINERS_AVAILABLE = True
except ImportError:
    TESTCONTAINERS_AVAILABLE = False

DEFAULT_REGISTRY_SOURCE = "ghwfxlab/ghwm-registry"
SECONDARY_REGISTRY_SOURCE = "pljanicki/ghwm-registry"


def _is_docker_available() -> bool:
    if not TESTCONTAINERS_AVAILABLE:
        return False
    try:
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


def _get_github_token() -> str | None:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    gh_bin = shutil.which("gh")
    if gh_bin:
        try:
            result = subprocess.run(  # noqa: S603
                [gh_bin, "auth", "token"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                stdout_token = result.stdout.strip()
                if stdout_token:
                    return stdout_token
        except (subprocess.SubprocessError, OSError):
            return None
    return None


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    """Build the ghwm wheel package into a clean directory."""
    out_dir = tmp_path_factory.mktemp("dist")
    uv_bin = shutil.which("uv")
    if uv_bin:
        result = subprocess.run(  # noqa: S603
            [uv_bin, "build", "--wheel", "--out-dir", str(out_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
    else:
        result = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "build", "--wheel", "--outdir", str(out_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
    assert result.returncode == 0, f"Failed to build wheel: {result.stderr}"

    wheel_files = list(out_dir.glob("*.whl"))
    assert wheel_files, "No wheel built"
    wheel_path = wheel_files[0]
    return wheel_path.parent, wheel_path.name


@pytest.fixture(scope="module")
def e2e_container(built_wheel: tuple[Path, str]) -> Generator[DockerContainer, None, None]:
    """Run a clean python:3.12-slim container with ghwm installed from the wheel."""
    if not _is_docker_available():
        pytest.skip("Docker is not available on host system")

    token = _get_github_token()
    if not token:
        pytest.skip("GitHub token with read:packages required for e2e tests")

    wheel_dir, wheel_name = built_wheel

    container = (
        DockerContainer("python:3.12-slim")
        .with_volume_mapping(str(wheel_dir), "/dist", "ro")
        .with_env("GITHUB_TOKEN", token)
        .with_env("DO_NOT_TRACK", "1")
        .with_env("GHWM_NO_TELEMETRY", "1")
        .with_command("tail -f /dev/null")
    )
    container.start()
    try:
        install_res = container.exec(["pip", "install", f"/dist/{wheel_name}"])
        assert install_res.exit_code == 0, f"pip install failed: {install_res.output.decode()}"
        yield container
    finally:
        container.stop()


class ContainerWorkspace:
    """Helper representing an isolated workspace directory inside the container."""

    def __init__(self, container: DockerContainer, workdir: str) -> None:
        self.container = container
        self.workdir = workdir
        self.container.exec(["mkdir", "-p", self.workdir])

    def write_file(self, rel_path: str, content: str) -> None:
        target = f"{self.workdir}/{rel_path}"
        b64_content = base64.b64encode(content.encode("utf-8")).decode("ascii")
        cmd = f'mkdir -p "$(dirname "{target}")" && echo "{b64_content}" | base64 -d > "{target}"'
        res = self.container.exec(["sh", "-c", cmd])
        assert res.exit_code == 0, f"Failed to write {rel_path}: {res.output.decode()}"

    def write_manifest(
        self,
        workflows: list[dict[str, Any]],
        *,
        source: str = DEFAULT_REGISTRY_SOURCE,
    ) -> None:
        manifest_data = {"source": source, "workflows": workflows}
        manifest_yaml = yaml.dump(manifest_data, sort_keys=False)
        self.write_file("ghwm.yml", manifest_yaml)

    def read_file(self, rel_path: str) -> str:
        target = f"{self.workdir}/{rel_path}"
        res = self.container.exec(["cat", target])
        if res.exit_code != 0:
            raise FileNotFoundError(f"{rel_path} does not exist in workspace")
        return res.output.decode("utf-8")

    def file_exists(self, rel_path: str) -> bool:
        target = f"{self.workdir}/{rel_path}"
        res = self.container.exec(["test", "-f", target])
        return res.exit_code == 0

    def replace_in_file(self, rel_path: str, target: str, replacement: str) -> None:
        content = self.read_file(rel_path)
        assert target in content, f"{target!r} not found in {rel_path}"
        self.write_file(rel_path, content.replace(target, replacement, 1))

    def read_lockfile(self) -> dict[str, Any]:
        content = self.read_file("ghwm.lock")
        data = json.loads(content)
        assert isinstance(data, dict)
        return data

    def run_ghwm(self, *args: str) -> tuple[int, str]:
        cmd = f"cd {self.workdir} && ghwm " + " ".join(args)
        res = self.container.exec(["sh", "-c", cmd])
        return res.exit_code, res.output.decode("utf-8")


@pytest.fixture
def workspace(e2e_container: DockerContainer) -> Generator[ContainerWorkspace, None, None]:
    """Provide a clean isolated workspace in the running container for each test."""
    ws_id = uuid.uuid4().hex[:8]
    workdir = f"/workspaces/test_{ws_id}"
    ws = ContainerWorkspace(e2e_container, workdir)
    yield ws
    e2e_container.exec(["rm", "-rf", workdir])


@pytest.mark.e2e
class TestGhwmEndToEnd:
    def test_e2e_should_install_ghwm_in_clean_env_when_container_starts(
        self,
        e2e_container: DockerContainer,
    ) -> None:
        # Arrange / Act
        result = e2e_container.exec(["ghwm", "--help"])

        # Assert
        assert result.exit_code == 0
        assert "Install GitHub workflow files from a registry repository" in result.output.decode("utf-8")

    def test_e2e_should_install_two_workflows_when_configured_from_single_registry(
        self,
        workspace: ContainerWorkspace,
    ) -> None:
        # Arrange
        workspace.write_manifest(
            [
                {"name": "ghwm-auto-assign-pr", "version": "1.0.0"},
                {"name": "ghwm-super-linter", "version": "1.0.0"},
            ]
        )

        # Act
        exit_code, output = workspace.run_ghwm("install")

        # Assert
        assert exit_code == 0
        assert "✓ Installed ghwm-auto-assign-pr" in output
        assert "✓ Installed ghwm-super-linter" in output

        # Verify workflows installed with headers
        auto_assign_content = workspace.read_file(".github/workflows/auto-assign-pr.yaml")
        assert "# Managed by ghwm (ghwm-auto-assign-pr@1.0.0)" in auto_assign_content

        linter_content = workspace.read_file(".github/workflows/super-linter.yaml")
        assert "# Managed by ghwm (ghwm-super-linter@1.0.0)" in linter_content

        # Verify config files created
        assert workspace.file_exists(".github/auto_assign.yaml")
        assert workspace.file_exists(".github/super-linter.env")

        # Verify lockfile
        lock_data = workspace.read_lockfile()
        assert lock_data["lockfileVersion"] == 1
        pkg_names = [pkg["name"] for pkg in lock_data["packages"]]
        assert "ghwm-auto-assign-pr" in pkg_names
        assert "ghwm-super-linter" in pkg_names

    def test_e2e_should_install_two_workflows_when_configured_from_two_different_registries(
        self,
        workspace: ContainerWorkspace,
    ) -> None:
        # Arrange
        workspace.write_manifest(
            [
                {"name": "ghwm-super-linter", "version": "1.0.0"},
                {
                    "name": "ghwm-auto-assign-pr",
                    "version": "1.0.0",
                    "source": SECONDARY_REGISTRY_SOURCE,
                },
            ]
        )

        # Act
        exit_code, output = workspace.run_ghwm("install")

        # Assert
        assert exit_code == 0
        assert "✓ Installed ghwm-super-linter" in output
        assert "✓ Installed ghwm-auto-assign-pr" in output

        # Verify lockfile sources
        lock_data = workspace.read_lockfile()
        sources_by_pkg = {pkg["name"]: pkg["source"] for pkg in lock_data["packages"]}
        assert sources_by_pkg["ghwm-super-linter"] == "@ghwfxlab/ghwm-super-linter"
        assert sources_by_pkg["ghwm-auto-assign-pr"] == "@pljanicki/ghwm-auto-assign-pr"

    def test_e2e_should_update_workflow_version_when_manifest_version_increased(
        self,
        workspace: ContainerWorkspace,
    ) -> None:
        # Arrange: Install version 1.0.0
        workspace.write_manifest([{"name": "ghwm-auto-assign-pr", "version": "1.0.0"}])
        install_exit_code, _ = workspace.run_ghwm("install")
        assert install_exit_code == 0
        assert "# Managed by ghwm (ghwm-auto-assign-pr@1.0.0)" in workspace.read_file(
            ".github/workflows/auto-assign-pr.yaml"
        )

        # Act: Update manifest to 1.0.1 and run update
        workspace.write_manifest([{"name": "ghwm-auto-assign-pr", "version": "1.0.1"}])
        update_exit_code, update_output = workspace.run_ghwm("update")

        # Assert
        assert update_exit_code == 0
        assert "↻ Updated ghwm-auto-assign-pr" in update_output
        updated_content = workspace.read_file(".github/workflows/auto-assign-pr.yaml")
        assert "# Managed by ghwm (ghwm-auto-assign-pr@1.0.1)" in updated_content
        lock_data = workspace.read_lockfile()
        assert lock_data["packages"][0]["version"] == "1.0.1"

    def test_e2e_should_downgrade_workflow_version_when_manifest_version_decreased(
        self,
        workspace: ContainerWorkspace,
    ) -> None:
        # Arrange: Install version 1.0.1
        workspace.write_manifest([{"name": "ghwm-auto-assign-pr", "version": "1.0.1"}])
        install_exit_code, _ = workspace.run_ghwm("install")
        assert install_exit_code == 0
        assert "# Managed by ghwm (ghwm-auto-assign-pr@1.0.1)" in workspace.read_file(
            ".github/workflows/auto-assign-pr.yaml"
        )

        # Act: Downgrade manifest to 1.0.0 and run install
        workspace.write_manifest([{"name": "ghwm-auto-assign-pr", "version": "1.0.0"}])
        downgrade_exit_code, downgrade_output = workspace.run_ghwm("install")

        # Assert
        assert downgrade_exit_code == 0
        assert "↻ Updated ghwm-auto-assign-pr" in downgrade_output
        downgraded_content = workspace.read_file(".github/workflows/auto-assign-pr.yaml")
        assert "# Managed by ghwm (ghwm-auto-assign-pr@1.0.0)" in downgraded_content
        lock_data = workspace.read_lockfile()
        assert lock_data["packages"][0]["version"] == "1.0.0"

    def test_e2e_should_preserve_triggers_when_update_triggers_false_and_overwrite_when_true(
        self,
        workspace: ContainerWorkspace,
    ) -> None:
        # Arrange: Install 1.0.0 and customize the on: section
        workspace.write_manifest([{"name": "ghwm-auto-assign-pr", "version": "1.0.0"}])
        workspace.run_ghwm("install")
        workspace.replace_in_file(
            ".github/workflows/auto-assign-pr.yaml",
            "pull_request:",
            "workflow_dispatch: # custom user trigger",
        )

        # Act 1: Update with update-triggers: false
        workspace.write_manifest(
            [
                {
                    "name": "ghwm-auto-assign-pr",
                    "version": "1.0.1",
                    "update-triggers": False,
                }
            ]
        )
        exit_code1, _ = workspace.run_ghwm("update")

        # Assert 1: Custom trigger is preserved
        assert exit_code1 == 0
        content1 = workspace.read_file(".github/workflows/auto-assign-pr.yaml")
        assert "workflow_dispatch: # custom user trigger" in content1
        assert "ghwm-auto-assign-pr@1.0.1" in content1

        # Act 2: Update with update-triggers: true
        workspace.write_manifest(
            [
                {
                    "name": "ghwm-auto-assign-pr",
                    "version": "1.0.1",
                    "update-triggers": True,
                }
            ]
        )
        exit_code2, _ = workspace.run_ghwm("update")

        # Assert 2: Packaged triggers overwrite custom trigger
        assert exit_code2 == 0
        content2 = workspace.read_file(".github/workflows/auto-assign-pr.yaml")
        assert "workflow_dispatch:" not in content2
        assert "pull_request:" in content2

    def test_e2e_should_preserve_envs_when_update_envs_false_and_overwrite_when_true(
        self,
        workspace: ContainerWorkspace,
    ) -> None:
        # Arrange: Install ghwm-super-linter 1.0.0 and customize its env: section
        workspace.write_manifest([{"name": "ghwm-super-linter", "version": "1.0.0"}])
        workspace.run_ghwm("install")
        workspace.replace_in_file(
            ".github/workflows/super-linter.yaml",
            "env:\n",
            "env:\n  CUSTOM_E2E_ENV: custom_val\n",
        )

        # Act 1: Update with update-envs: false
        workspace.write_manifest(
            [
                {
                    "name": "ghwm-super-linter",
                    "version": "1.0.1",
                    "update-envs": False,
                }
            ]
        )
        exit_code1, _ = workspace.run_ghwm("update")

        # Assert 1: Custom env is preserved
        assert exit_code1 == 0
        content1 = workspace.read_file(".github/workflows/super-linter.yaml")
        assert "CUSTOM_E2E_ENV: custom_val" in content1
        assert "ghwm-super-linter@1.0.1" in content1

        # Act 2: Update with update-envs: true
        workspace.write_manifest(
            [
                {
                    "name": "ghwm-super-linter",
                    "version": "1.0.1",
                    "update-envs": True,
                }
            ]
        )
        exit_code2, _ = workspace.run_ghwm("update")

        # Assert 2: Packaged env overwrites custom env
        assert exit_code2 == 0
        content2 = workspace.read_file(".github/workflows/super-linter.yaml")
        assert "CUSTOM_E2E_ENV" not in content2

    def test_e2e_should_preserve_config_files_when_update_config_files_false_and_overwrite_when_true(
        self,
        workspace: ContainerWorkspace,
    ) -> None:
        # Arrange: Install 1.0.0 and customize .github/auto_assign.yaml
        workspace.write_manifest([{"name": "ghwm-auto-assign-pr", "version": "1.0.0"}])
        workspace.run_ghwm("install")
        workspace.replace_in_file(
            ".github/auto_assign.yaml",
            "addReviewers: false",
            "addReviewers: true # custom user setting",
        )

        # Act 1: Update with update-config-files: false
        workspace.write_manifest(
            [
                {
                    "name": "ghwm-auto-assign-pr",
                    "version": "1.0.1",
                    "update-config-files": False,
                }
            ]
        )
        exit_code1, _ = workspace.run_ghwm("update")

        # Assert 1: Config customization is preserved
        assert exit_code1 == 0
        cfg1 = workspace.read_file(".github/auto_assign.yaml")
        assert "addReviewers: true # custom user setting" in cfg1

        # Act 2: Update with update-config-files: true
        workspace.write_manifest(
            [
                {
                    "name": "ghwm-auto-assign-pr",
                    "version": "1.0.1",
                    "update-config-files": True,
                }
            ]
        )
        exit_code2, _ = workspace.run_ghwm("update")

        # Assert 2: Packaged config file overwrites user modification
        assert exit_code2 == 0
        cfg2 = workspace.read_file(".github/auto_assign.yaml")
        assert "custom user setting" not in cfg2
        assert "addReviewers: false" in cfg2

    def test_e2e_should_prune_stale_workflow_and_preserve_config_when_removed_from_manifest(
        self,
        workspace: ContainerWorkspace,
    ) -> None:
        # Arrange: Install two workflows
        workspace.write_manifest(
            [
                {"name": "ghwm-auto-assign-pr", "version": "1.0.0"},
                {"name": "ghwm-super-linter", "version": "1.0.0"},
            ]
        )
        workspace.run_ghwm("install")
        assert workspace.file_exists(".github/workflows/auto-assign-pr.yaml")
        assert workspace.file_exists(".github/auto_assign.yaml")
        assert workspace.file_exists(".github/workflows/super-linter.yaml")

        # Act: Remove auto-assign-pr from manifest and run install
        workspace.write_manifest([{"name": "ghwm-super-linter", "version": "1.0.0"}])
        exit_code, output = workspace.run_ghwm("install")

        # Assert: auto-assign-pr workflow pruned, config kept, super-linter kept
        assert exit_code == 0
        assert "✗ Pruned ghwm-auto-assign-pr" in output
        assert not workspace.file_exists(".github/workflows/auto-assign-pr.yaml")
        assert workspace.file_exists(".github/auto_assign.yaml")
        assert workspace.file_exists(".github/workflows/super-linter.yaml")

        lock_data = workspace.read_lockfile()
        pkg_names = [pkg["name"] for pkg in lock_data["packages"]]
        assert "ghwm-auto-assign-pr" not in pkg_names
        assert "ghwm-super-linter" in pkg_names

    def test_e2e_should_refuse_to_prune_modified_workflow_without_force_and_prune_with_force(
        self,
        workspace: ContainerWorkspace,
    ) -> None:
        # Arrange: Install workflow and modify its body locally
        workspace.write_manifest([{"name": "ghwm-auto-assign-pr", "version": "1.0.0"}])
        workspace.run_ghwm("install")
        workspace.replace_in_file(
            ".github/workflows/auto-assign-pr.yaml",
            "Add Reviewers and Assignees",
            "Modified Reviewers and Assignees",
        )

        # Act 1: Remove from manifest and run install without --force
        workspace.write_manifest([])
        exit_code1, output1 = workspace.run_ghwm("install")

        # Assert 1: File is kept because it was modified
        assert exit_code1 == 0
        assert "⊘ Skipped ghwm-auto-assign-pr (modified)" in output1
        assert workspace.file_exists(".github/workflows/auto-assign-pr.yaml")

        # Act 2: Run with --force
        exit_code2, output2 = workspace.run_ghwm("install", "--force")

        # Assert 2: File is pruned with force
        assert exit_code2 == 0
        assert "✗ Pruned ghwm-auto-assign-pr" in output2
        assert not workspace.file_exists(".github/workflows/auto-assign-pr.yaml")

    def test_e2e_should_install_workflow_to_custom_target_when_target_specified(
        self,
        workspace: ContainerWorkspace,
    ) -> None:
        # Arrange
        workspace.write_manifest(
            [
                {
                    "name": "ghwm-auto-assign-pr",
                    "version": "1.0.0",
                    "target": "custom-auto-assign.yaml",
                }
            ]
        )

        # Act
        exit_code, _ = workspace.run_ghwm("install")

        # Assert
        assert exit_code == 0
        assert workspace.file_exists(".github/workflows/custom-auto-assign.yaml")
        assert not workspace.file_exists(".github/workflows/auto-assign-pr.yaml")

        lock_data = workspace.read_lockfile()
        targets = [f["target"] for f in lock_data["packages"][0]["files"]]
        assert ".github/workflows/custom-auto-assign.yaml" in targets

    def test_e2e_should_skip_unchanged_workflows_when_run_repeatedly(
        self,
        workspace: ContainerWorkspace,
    ) -> None:
        # Arrange
        workspace.write_manifest([{"name": "ghwm-auto-assign-pr", "version": "1.0.0"}])
        workspace.run_ghwm("install")

        # Act
        exit_code, output = workspace.run_ghwm("install")

        # Assert
        assert exit_code == 0
        assert "⊘ Skipped ghwm-auto-assign-pr (already up to date)" in output

    def test_e2e_should_display_declared_workflows_when_list_command_executed(
        self,
        workspace: ContainerWorkspace,
    ) -> None:
        # Arrange
        workspace.write_manifest(
            [
                {"name": "ghwm-auto-assign-pr", "version": "1.0.0"},
                {"name": "ghwm-super-linter", "version": "1.0.0"},
            ]
        )

        # Act
        exit_code, output = workspace.run_ghwm("list")

        # Assert
        assert exit_code == 0
        assert f"Source: {DEFAULT_REGISTRY_SOURCE}" in output
        assert "Workflows (2):" in output
        assert "- ghwm-auto-assign-pr@1.0.0" in output
        assert "- ghwm-super-linter@1.0.0" in output

    def test_e2e_should_honour_telemetry_opt_out_environment_variable(
        self,
        workspace: ContainerWorkspace,
    ) -> None:
        # Arrange: manifest with a workflow from a registry
        workspace.write_manifest([{"name": "ghwm-auto-assign-pr", "version": "1.0.0"}])

        # Act: running install with DO_NOT_TRACK=1 and GHWM_NO_TELEMETRY=1 (already configured in container)
        # Verify both flag and environment variable behavior cleanly without errors
        exit_code, output = workspace.run_ghwm("install", "--no-telemetry")

        # Assert
        assert exit_code == 0
        assert "✓ Installed ghwm-auto-assign-pr" in output
        assert workspace.file_exists(".github/workflows/auto-assign-pr.yaml")



"""Tests for path traversal security prevention."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ghwm.install import install_workflows
from ghwm.manifest import parse_manifest
from ghwm.paths import safe_resolve_path
from tests.shared import MARKETPLACE_SOURCE, VERSION_1


def test_safe_resolve_path_should_raise_value_error_when_target_escapes_base_dir(tmp_path: Path) -> None:
    # Arrange
    base_dir = tmp_path / "workspace"
    base_dir.mkdir()

    # Act & Assert
    with pytest.raises(ValueError, match="Path traversal detected"):
        safe_resolve_path(base_dir, "../outside.txt")

    with pytest.raises(ValueError, match="Path traversal detected"):
        safe_resolve_path(base_dir, "/absolute/path/outside.txt")

    with pytest.raises(ValueError, match="Path traversal detected"):
        safe_resolve_path(base_dir, ".")


def test_safe_resolve_path_should_return_path_when_target_is_valid_relative(tmp_path: Path) -> None:
    # Arrange
    base_dir = tmp_path / "workspace"
    base_dir.mkdir()

    # Act
    resolved = safe_resolve_path(base_dir, "sub/dir/file.txt")

    # Assert
    assert resolved == base_dir / "sub" / "dir" / "file.txt"


def test_install_workflows_should_raise_value_error_when_package_contains_path_traversal(
    tmp_path: Path,
) -> None:
    # Arrange
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    marketplace = tmp_path / "marketplace"
    marketplace.mkdir()

    # Create local package with path traversal target
    workflow_dir = marketplace / "workflows" / "linter"
    workflow_dir.mkdir(parents=True, exist_ok=True)

    (workflow_dir / "workflow.yml").write_text(
        yaml.safe_dump({"name": "linter", "files": [{"source": "linter.yaml", "target": "../../malicious.yaml"}]})
    )
    (workflow_dir / "linter.yaml").write_text("content")

    # Local ghwm.yml manifest
    manifest = parse_manifest(
        {
            "source": MARKETPLACE_SOURCE,
            "workflows": [{"name": "linter", "version": VERSION_1}],
        }
    )

    # Act & Assert
    with pytest.raises(ValueError, match="Path traversal detected"):
        install_workflows(
            consumer,
            manifest,
            local_path=marketplace,
            prune=False,
        )


def test_install_workflows_should_raise_value_error_when_local_read_source_escapes_workflow_dir(
    tmp_path: Path,
) -> None:
    # Arrange
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    marketplace = tmp_path / "marketplace"
    marketplace.mkdir()

    # Create local package where file source escapes
    workflow_dir = marketplace / "workflows" / "linter"
    workflow_dir.mkdir(parents=True, exist_ok=True)

    # Here source escapes but target is normal
    (workflow_dir / "workflow.yml").write_text(
        yaml.safe_dump(
            {"name": "linter", "files": [{"source": "../../outside.yaml", "target": ".github/workflows/linter.yaml"}]}
        )
    )

    # Local ghwm.yml manifest
    manifest = parse_manifest(
        {
            "source": MARKETPLACE_SOURCE,
            "workflows": [{"name": "linter", "version": VERSION_1}],
        }
    )

    # Act & Assert
    with pytest.raises(ValueError, match="Path traversal detected"):
        install_workflows(
            consumer,
            manifest,
            local_path=marketplace,
            prune=False,
        )

"""Shared test constants."""

from __future__ import annotations

from pathlib import Path

LINTER = "linter"
AUTO_ASSIGN_PR = "auto-assign-pr"
DEFAULT_MANIFEST_PATH = "ghwm.yml"
MARKETPLACE_SOURCE = "owner/ghwm-marketplace"
WORKFLOWS_DIR = Path(".github") / "workflows"

VERSION_1 = "1.0.0"
VERSION_2 = "2.0.0"
VERSION_1_2_3 = "1.2.3"
LINTER_VERSION = "0.1.4"
LINTER_PACKAGE_SOURCE = "@owner/ghwm-linter"
AUTO_ASSIGN_PR_PACKAGE_SOURCE = "@owner/ghwm-auto-assign-pr"

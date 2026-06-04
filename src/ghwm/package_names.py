"""Helpers for workflow package naming."""

from __future__ import annotations


def package_basename(workflow_name: str) -> str:
    """Return the unscoped npm package name for a workflow."""
    return f"ghwm-{workflow_name}"


def scoped_package_name(org: str, workflow_name: str) -> str:
    """Return the scoped npm package name for a workflow."""
    return f"@{org}/{package_basename(workflow_name)}"

"""Path security utilities."""

from __future__ import annotations

import os
from pathlib import Path


def safe_resolve_path(base_dir: Path, target: str) -> Path:
    """Resolve target path relative to base_dir, ensuring it remains under base_dir."""
    abs_base = os.path.abspath(base_dir)
    abs_target = os.path.abspath(os.path.join(abs_base, target))

    prefix = abs_base if abs_base.endswith(os.sep) else abs_base + os.sep
    if not abs_target.startswith(prefix):
        raise ValueError(f"Path traversal detected: '{target}' resolves outside of base directory '{base_dir}'")
    return Path(abs_target)

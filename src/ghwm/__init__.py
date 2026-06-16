"""ghwm — Install GitHub workflow files from a registry repository."""

from importlib.metadata import PackageNotFoundError, version

PACKAGE_NAME = "ghwm"

try:
    __version__ = version(PACKAGE_NAME)
except PackageNotFoundError:
    __version__ = "0+unknown"

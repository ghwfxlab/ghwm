"""CLI entry point for ``ghwm``."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tarfile
from pathlib import Path
from urllib.error import HTTPError, URLError

import yaml

from ghwm import __version__
from ghwm.install import InstallResult, install_workflows, update_workflows
from ghwm.manifest import read_manifest

DEFAULT_COMMAND = "install"
DEFAULT_MANIFEST_PATH = "ghwm.yml"
DEFAULT_CWD = "."
MANIFEST_HELP = "Path to manifest file."
CWD_HELP = "Consumer repository root."
FORCE_HELP = "Overwrite unmanaged or modified files."
LOCAL_HELP = "Path to local marketplace checkout."
UPDATE_TRIGGERS_HELP = "Replace workflow triggers with the packaged version during updates."


def add_install_cmd_to_parser(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    install_cmd = subcommands.add_parser("install", help="Sync workflows to match the manifest (default).")
    install_cmd.add_argument("--manifest", default=DEFAULT_MANIFEST_PATH, help=MANIFEST_HELP)
    install_cmd.add_argument("--cwd", default=DEFAULT_CWD, help=CWD_HELP)
    install_cmd.add_argument("--force", action="store_true", help=FORCE_HELP)
    install_cmd.add_argument("--no-prune", action="store_true", help="Skip removal of stale workflows.")
    install_cmd.add_argument("--local", default=None, help=LOCAL_HELP)
    install_cmd.add_argument(
        "--update-triggers",
        action="store_true",
        help=UPDATE_TRIGGERS_HELP,
    )


def add_update_cmd_to_parser(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    update_cmd = subcommands.add_parser("update", help="Re-download and refresh all manifest workflows.")
    update_cmd.add_argument("--manifest", default=DEFAULT_MANIFEST_PATH, help=MANIFEST_HELP)
    update_cmd.add_argument("--cwd", default=DEFAULT_CWD, help=CWD_HELP)
    update_cmd.add_argument("--force", action="store_true", help=FORCE_HELP)
    update_cmd.add_argument(
        "--prune",
        action="store_true",
        help="Remove managed workflows that are no longer listed in the manifest.",
    )
    update_cmd.add_argument("--local", default=None, help=LOCAL_HELP)
    update_cmd.add_argument(
        "--update-triggers",
        action="store_true",
        help=UPDATE_TRIGGERS_HELP,
    )


def add_list_cmd_to_parser(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    list_cmd = subcommands.add_parser("list", help="Show workflows declared in the manifest.")
    list_cmd.add_argument("--manifest", default=DEFAULT_MANIFEST_PATH, help=MANIFEST_HELP)
    list_cmd.add_argument("--cwd", default=DEFAULT_CWD, help=CWD_HELP)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ghwm",
        description="Install GitHub workflow files from a marketplace repository.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    # Defaults for when no subcommand is given (falls back to "install")
    parser.set_defaults(
        command=None,
        manifest=DEFAULT_MANIFEST_PATH,
        cwd=DEFAULT_CWD,
        force=False,
        no_prune=False,
        local=None,
        update_triggers=False,
    )

    subcommands = parser.add_subparsers(dest="command")

    add_install_cmd_to_parser(subcommands)
    add_update_cmd_to_parser(subcommands)
    add_list_cmd_to_parser(subcommands)

    return parser


def print_result(result: InstallResult) -> None:
    for name in result.installed:
        print(f"  ✓ Installed {name}")
    for name in result.updated:
        print(f"  ↻ Updated {name}")
    for name in result.pruned:
        print(f"  ✗ Pruned {name}")
    for name, reason in result.skipped:
        print(f"  ⊘ Skipped {name} ({reason})")


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or DEFAULT_COMMAND

    try:
        cwd = Path(args.cwd).resolve()
        manifest_path = args.manifest
        local_path = Path(args.local) if args.local else None

        manifest = read_manifest(cwd, manifest_path)

        if command == "list":
            print(f"Source: {manifest.source}")
            print(f"\nWorkflows ({len(manifest.workflows)}):")
            for entry in manifest.workflows:
                print(f"  - {entry.install_spec}")
            return

        print(f"Found {len(manifest.workflows)} workflow(s) in {manifest_path}")

        if command == "install":
            result = install_workflows(
                cwd,
                manifest,
                force=args.force,
                prune=not args.no_prune,
                local_path=local_path,
                update_triggers=args.update_triggers,
            )
        elif command == "update":
            result = update_workflows(
                cwd,
                manifest,
                force=args.force,
                prune=args.prune,
                local_path=local_path,
                update_triggers=args.update_triggers,
            )
        else:
            raise AssertionError(f"Unexpected command: {command!r}")

        print_result(result)
        print("\nDone.")

    except (
        FileNotFoundError,
        ValueError,
        RuntimeError,
        subprocess.CalledProcessError,
        tarfile.TarError,
        HTTPError,
        URLError,
        yaml.YAMLError,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

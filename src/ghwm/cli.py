"""CLI entry point for ``ghwm``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from ghwm.install import InstallResult


DEFAULT_COMMAND = "install"
DEFAULT_MANIFEST_PATH = "ghwm.yml"
DEFAULT_CWD = "."
MANIFEST_HELP = "Path to manifest file."
CWD_HELP = "Consumer repository root."
FORCE_HELP = "Overwrite unmanaged or modified files."
LOCAL_HELP = "Path to local registry checkout."
UPDATE_TRIGGERS_HELP = "Replace workflow triggers with the packaged version during updates."
UPDATE_ENVS_HELP = "Replace workflow env variables with the packaged version during updates."
NO_TELEMETRY_HELP = "Disable telemetry for this run. Also honoured via DO_NOT_TRACK=1 or GHWM_NO_TELEMETRY=1."


def add_install_cmd_to_parser(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    install_cmd = subcommands.add_parser("install", help="Sync workflows to match the manifest (default).")
    install_cmd.add_argument("--manifest", default=DEFAULT_MANIFEST_PATH, help=MANIFEST_HELP)
    install_cmd.add_argument("--cwd", default=DEFAULT_CWD, help=CWD_HELP)
    install_cmd.add_argument("--force", action="store_true", help=FORCE_HELP)
    install_cmd.add_argument(
        "--no-prune",
        action="store_true",
        help="Do not remove workflows that are no longer listed in the manifest.",
    )
    install_cmd.add_argument("--local", default=None, help=LOCAL_HELP)
    install_cmd.add_argument(
        "--update-triggers",
        action="store_true",
        help=UPDATE_TRIGGERS_HELP,
    )
    install_cmd.add_argument(
        "--update-envs",
        action="store_true",
        help=UPDATE_ENVS_HELP,
    )
    install_cmd.add_argument(
        "--no-telemetry",
        action="store_true",
        help=NO_TELEMETRY_HELP,
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
    update_cmd.add_argument(
        "--update-envs",
        action="store_true",
        help=UPDATE_ENVS_HELP,
    )
    update_cmd.add_argument(
        "--no-telemetry",
        action="store_true",
        help=NO_TELEMETRY_HELP,
    )


def add_upgrade_cmd_to_parser(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    upgrade_cmd = subcommands.add_parser(
        "upgrade", help="Automatically upgrade all workflows to their newest published versions."
    )
    upgrade_cmd.add_argument("--manifest", default=DEFAULT_MANIFEST_PATH, help=MANIFEST_HELP)
    upgrade_cmd.add_argument("--cwd", default=DEFAULT_CWD, help=CWD_HELP)
    upgrade_cmd.add_argument("--force", action="store_true", help=FORCE_HELP)
    upgrade_cmd.add_argument(
        "--prune",
        action="store_true",
        help="Remove managed workflows that are no longer listed in the manifest.",
    )
    upgrade_cmd.add_argument("--local", default=None, help=LOCAL_HELP)
    upgrade_cmd.add_argument(
        "--update-triggers",
        action="store_true",
        help=UPDATE_TRIGGERS_HELP,
    )
    upgrade_cmd.add_argument(
        "--update-envs",
        action="store_true",
        help=UPDATE_ENVS_HELP,
    )
    upgrade_cmd.add_argument(
        "--no-telemetry",
        action="store_true",
        help=NO_TELEMETRY_HELP,
    )


def add_list_cmd_to_parser(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    list_cmd = subcommands.add_parser("list", help="Show workflows declared in the manifest.")
    list_cmd.add_argument("--manifest", default=DEFAULT_MANIFEST_PATH, help=MANIFEST_HELP)
    list_cmd.add_argument("--cwd", default=DEFAULT_CWD, help=CWD_HELP)


def add_audit_cmd_to_parser(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    audit_cmd = subcommands.add_parser("audit", help="Audit managed workflow files for security vulnerabilities.")
    audit_cmd.add_argument("--manifest", default=DEFAULT_MANIFEST_PATH, help=MANIFEST_HELP)
    audit_cmd.add_argument("--cwd", default=DEFAULT_CWD, help=CWD_HELP)


def build_parser() -> argparse.ArgumentParser:
    from ghwm import __version__

    parser = argparse.ArgumentParser(
        prog="ghwm",
        description="Install GitHub workflow files from a registry repository.",
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
        update_envs=False,
        no_telemetry=False,
    )

    subcommands = parser.add_subparsers(dest="command")

    add_install_cmd_to_parser(subcommands)
    add_update_cmd_to_parser(subcommands)
    add_upgrade_cmd_to_parser(subcommands)
    add_list_cmd_to_parser(subcommands)
    add_audit_cmd_to_parser(subcommands)

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


def run_audit(cwd: Path) -> None:
    """Audit managed workflows for security vulnerabilities using zizmor."""
    from ghwm.audit import run_audit as _run_audit

    _run_audit(cwd)


def _resolve_no_telemetry(flag: bool) -> bool:
    import os

    return flag or os.environ.get("DO_NOT_TRACK") == "1" or os.environ.get("GHWM_NO_TELEMETRY") == "1"


def _is_handled_exception(exc: Exception) -> bool:
    if isinstance(exc, (FileNotFoundError, ValueError, RuntimeError)):
        return True
    handled_types: list[type[BaseException]] = []
    if (sub := sys.modules.get("subprocess")) is not None:
        handled_types.append(sub.CalledProcessError)
    if (tar := sys.modules.get("tarfile")) is not None:
        handled_types.append(tar.TarError)
    if (yaml := sys.modules.get("yaml")) is not None:
        handled_types.append(yaml.YAMLError)
    if (urllib_err := sys.modules.get("urllib.error")) is not None:
        handled_types.extend((urllib_err.HTTPError, urllib_err.URLError))
    return bool(handled_types) and isinstance(exc, tuple(handled_types))


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or DEFAULT_COMMAND

    try:
        cwd = Path(args.cwd).resolve()
        manifest_path = args.manifest
        local_path = Path(args.local) if args.local else None

        if command == "audit":
            run_audit(cwd)
            return

        from ghwm.manifest import read_manifest

        manifest = read_manifest(cwd, manifest_path)

        if command == "list":
            print(f"Source: {manifest.source}")
            print(f"\nWorkflows ({len(manifest.workflows)}):")
            for entry in manifest.workflows:
                print(f"  - {entry.install_spec}")
            return

        latest_flag = command == "upgrade"
        needs_resolution = latest_flag or any(
            not entry.version or entry.version == "latest" for entry in manifest.workflows
        )
        if command in ("install", "update", "upgrade") and not local_path and needs_resolution:
            from dataclasses import replace

            from ghwm.download import github_token
            from ghwm.download_npm import resolve_latest_version
            from ghwm.manifest import rewrite_manifest_versions

            token = github_token()
            resolved = {}
            new_workflows = []
            for entry in manifest.workflows:
                if latest_flag or not entry.version or entry.version == "latest":
                    entry_source = entry.source or manifest.source
                    owner, _ = entry_source.split("/", 1)
                    print(f"Resolving latest version for {entry.name}...")
                    semver, githead = resolve_latest_version(owner, entry.name, token)
                    resolved[entry.name] = (semver, githead)
                    new_workflows.append(replace(entry, version=semver))
                else:
                    new_workflows.append(entry)

            if resolved:
                rewrite_manifest_versions(cwd, manifest_path, resolved)
            manifest = replace(manifest, workflows=new_workflows)

        print(f"Found {len(manifest.workflows)} workflow(s) in {manifest_path}")

        no_telemetry = _resolve_no_telemetry(args.no_telemetry)

        if command == "install":
            from ghwm.install import install_workflows

            result = install_workflows(
                cwd,
                manifest,
                force=args.force,
                prune=not args.no_prune,
                local_path=local_path,
                update_triggers=args.update_triggers,
                update_envs=args.update_envs,
                no_telemetry=no_telemetry,
            )
        elif command in ("update", "upgrade"):
            from ghwm.install import update_workflows

            result = update_workflows(
                cwd,
                manifest,
                force=args.force,
                prune=args.prune,
                local_path=local_path,
                update_triggers=args.update_triggers,
                update_envs=args.update_envs,
                no_telemetry=no_telemetry,
            )
        else:
            raise AssertionError(f"Unexpected command: {command!r}")

        print_result(result)
        print("\nDone.")

    except Exception as exc:
        if _is_handled_exception(exc):
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        raise

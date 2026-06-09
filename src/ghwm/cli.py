"""CLI entry point for ``ghwm``."""

from __future__ import annotations

import argparse
import json
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


def add_audit_cmd_to_parser(subcommands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    audit_cmd = subcommands.add_parser("audit", help="Audit managed workflow files for security vulnerabilities.")
    audit_cmd.add_argument("--manifest", default=DEFAULT_MANIFEST_PATH, help=MANIFEST_HELP)
    audit_cmd.add_argument("--cwd", default=DEFAULT_CWD, help=CWD_HELP)


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
    from ghwm.lock import read_lockfile

    lockfile = read_lockfile(cwd)
    if not lockfile.packages:
        print("Error: No workflows installed. Please run 'ghwm install' first.", file=sys.stderr)
        sys.exit(1)

    files_to_audit = []
    for package in lockfile.packages:
        for file_entry in package.files:
            if file_entry.target.startswith(".github/workflows/"):
                target_path = cwd / file_entry.target
                if target_path.is_file():
                    files_to_audit.append(str(target_path))

    if not files_to_audit:
        print("No managed workflow files found to audit.")
        return

    cmd = ["zizmor", "--format", "json", *files_to_audit]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    except FileNotFoundError:
        cmd = ["uvx", "zizmor", "--format", "json", *files_to_audit]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
        except FileNotFoundError as exc:
            raise RuntimeError(
                "zizmor linter is not installed and 'uvx' is not available. "
                "Please install zizmor (https://docs.zizmor.sh) or uv (https://astral.sh/uv) to run audits."
            ) from exc

    if res.returncode != 0 and not res.stdout.strip().startswith("["):
        error_msg = res.stderr.strip() or res.stdout.strip()
        raise RuntimeError(f"zizmor execution failed: {error_msg}")

    try:
        findings = json.loads(res.stdout) if res.stdout.strip() else []
    except json.JSONDecodeError as exc:
        error_msg = res.stderr.strip() or res.stdout.strip()
        if error_msg:
            raise RuntimeError(f"zizmor execution failed: {error_msg}") from exc
        findings = []

    score = 100
    active_findings = []
    severity_counts = {"High": 0, "Medium": 0, "Low": 0, "Informational": 0}

    for finding in findings:
        if finding.get("ignored", False):
            continue
        active_findings.append(finding)

        determinations = finding.get("determinations", {})
        severity = determinations.get("severity", "Low")
        sev_key = severity.title()
        if sev_key in severity_counts:
            severity_counts[sev_key] += 1
        else:
            severity_counts["Low"] += 1

    score -= severity_counts["High"] * 20
    score -= severity_counts["Medium"] * 10
    score -= severity_counts["Low"] * 5
    score -= severity_counts["Informational"] * 1
    score = max(0, score)

    if active_findings:
        print(f"Auditing {len(files_to_audit)} managed workflow file(s)...")
        print("\nSecurity Findings:")
        print("-" * 60)
        for finding in active_findings:
            ident = finding.get("ident")
            desc = finding.get("desc")
            determinations = finding.get("determinations", {})
            severity = determinations.get("severity", "Low").upper()
            confidence = determinations.get("confidence", "Medium").upper()

            locations = finding.get("locations", [])
            location_str = "unknown location"
            if locations:
                loc = locations[0]
                symbolic = loc.get("symbolic", {})
                concrete = loc.get("concrete", {})

                key = symbolic.get("key", {})
                local = key.get("Local", {})
                given_path = local.get("given_path", "unknown file")

                loc_details = concrete.get("location", {})
                start_point = loc_details.get("start_point", {})
                row = start_point.get("row")
                line_str = f":{row + 1}" if row is not None else ""
                location_str = f"{given_path}{line_str}"

            print(f"[{severity}] {ident}: {desc}")
            print(f"  Location:   {location_str}")
            print(f"  Confidence: {confidence}")
            print()

        print("-" * 60)
        print(f"Audit completed: {len(active_findings)} finding(s)")
        print(f"  High:          {severity_counts['High']}")
        print(f"  Medium:        {severity_counts['Medium']}")
        print(f"  Low:           {severity_counts['Low']}")
        print(f"  Informational: {severity_counts['Informational']}")
        print(f"\nSecurity Score: {score}/100")

        if severity_counts["High"] > 0 or severity_counts["Medium"] > 0:
            sys.exit(1)
    else:
        print(f"Auditing {len(files_to_audit)} managed workflow file(s)...")
        print("\nNo security findings reported. Good job!")
        print(f"Security Score: {score}/100")


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

        if command == "audit":
            run_audit(cwd)
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

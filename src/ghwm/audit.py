"""Audit managed workflows for security vulnerabilities using zizmor."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from ghwm.lock import read_lockfile

HIGH_DEDUCTION = 20
MEDIUM_DEDUCTION = 10
LOW_DEDUCTION = 5
INFORMATIONAL_DEDUCTION = 1

RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
RESET = "\033[0m"

SEVERITY_COLORS = {
    "HIGH": RED,
    "MEDIUM": YELLOW,
    "LOW": GREEN,
    "INFORMATIONAL": BLUE,
}


def _run_zizmor(files_to_audit: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = ["zizmor", "--format", "json", *files_to_audit]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    except FileNotFoundError:
        cmd = ["uvx", "zizmor", "--format", "json", *files_to_audit]
        try:
            return subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
        except FileNotFoundError as exc:
            raise RuntimeError(
                "zizmor linter is not installed and 'uvx' is not available. "
                "Please install zizmor (https://docs.zizmor.sh) or uv (https://astral.sh/uv) to run audits."
            ) from exc


def _get_findings(res: subprocess.CompletedProcess[str]) -> list[dict[str, Any]]:
    if res.returncode != 0 and not res.stdout.strip().startswith("["):
        error_msg = res.stderr.strip() or res.stdout.strip()
        raise RuntimeError(f"zizmor execution failed: {error_msg}")

    try:
        data = json.loads(res.stdout) if res.stdout.strip() else []
        return cast(list[dict[str, Any]], data)
    except json.JSONDecodeError as exc:
        error_msg = res.stderr.strip() or res.stdout.strip()
        raise RuntimeError(f"zizmor execution failed: {error_msg}") from exc


def _get_score_from_findings(severity_counts: dict[str, int]) -> int:
    deductions = (
        severity_counts.get("High", 0) * HIGH_DEDUCTION
        + severity_counts.get("Medium", 0) * MEDIUM_DEDUCTION
        + severity_counts.get("Low", 0) * LOW_DEDUCTION
        + severity_counts.get("Informational", 0) * INFORMATIONAL_DEDUCTION
    )
    return round(100 * math.exp(-deductions / 100))


def _print_findings(
    files_to_audit: list[str],
    active_findings: list[dict[str, Any]],
    severity_counts: dict[str, int],
    score: int,
) -> None:
    is_atty = sys.stdout.isatty()

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

            if is_atty and severity in SEVERITY_COLORS:
                colored_sev = f"{SEVERITY_COLORS[severity]}[{severity}]{RESET}"
            else:
                colored_sev = f"[{severity}]"

            print(f"{colored_sev} {ident}: {desc}")
            print(f"  Location:   {location_str}")
            print(f"  Confidence: {confidence}")
            print()

        print("-" * 60)
        print(f"Audit completed: {len(active_findings)} finding(s)")
        print(f"  High:          {severity_counts['High']}")
        print(f"  Medium:        {severity_counts['Medium']}")
        print(f"  Low:           {severity_counts['Low']}")
        print(f"  Informational: {severity_counts['Informational']}")

        if is_atty:
            if severity_counts["High"] > 0:
                score_color = RED
            elif severity_counts["Medium"] > 0:
                score_color = YELLOW
            else:
                score_color = GREEN
            print(f"\n{score_color}Security Score: {score}/100{RESET}")
        else:
            print(f"\nSecurity Score: {score}/100")

        if severity_counts["High"] > 0 or severity_counts["Medium"] > 0:
            sys.exit(1)
    else:
        print(f"Auditing {len(files_to_audit)} managed workflow file(s)...")
        if is_atty:
            print(f"\n{GREEN}No security findings reported. Good job!{RESET}")
            print(f"{GREEN}Security Score: {score}/100{RESET}")
        else:
            print("\nNo security findings reported. Good job!")
            print(f"Security Score: {score}/100")


def run_audit(cwd: Path) -> None:
    """Audit managed workflows for security vulnerabilities using zizmor."""
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

    res = _run_zizmor(files_to_audit)
    findings = _get_findings(res)

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

    score = _get_score_from_findings(severity_counts)

    _print_findings(files_to_audit, active_findings, severity_counts, score)

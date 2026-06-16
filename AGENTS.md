# AGENTS.md

## Purpose

`ghwm` is a Python CLI that installs managed GitHub Actions workflow packages
from a registry repository into a consumer repository.

The core lifecycle is:

1. Read `ghwm.yml`
2. Resolve package versions and workflow settings
3. Download or read workflow package files
4. Install rendered workflow files plus packaged config files
5. Maintain `ghwm.lock`

Read `docs/ARCHITECTURE.md` before making structural changes.

## Agent skills

To guide automated developer agents, this repository provides pre-configured workspace skills under `.agents/skills/`:

- [python-coding-standards](.agents/skills/python-coding-standards/SKILL.md): Reusable Python coding standards for implementation, refactoring, and code review (typing, error handling, subprocess safety, etc.).
- [testing-standards](.agents/skills/testing-standards/SKILL.md): Reusable test-writing and test-review guidance (Arrange/Act/Assert, mock isolation, naming conventions).

Agents should read and follow these standards for all contributions.

## Repository layout

- `src/ghwm/cli.py` - argparse entry point and user-facing command flow
- `src/ghwm/manifest.py` - manifest parsing and workflow/package resolution
- `src/ghwm/download.py` - package download orchestration and local checkout reads
- `src/ghwm/download_npm.py` - GitHub Packages tarball download and package extraction
- `src/ghwm/install.py` - install/update/prune orchestration
- `src/ghwm/managed_files.py` - low-level workflow/config sync, trigger merge, and prune checks
- `src/ghwm/lock.py` - lockfile read/write and in-memory lockfile operations
- `src/ghwm/__main__.py` - `python -m ghwm` entry point
- `tests/` - module-aligned pytest suite
- `docs/ARCHITECTURE.md` - architecture and lifecycle notes

## Development commands

Use the existing Make targets:

- `make install` - sync dependencies with `uv`
- `make test` - run pytest with coverage
- `make lint` - run Ruff
- `make type-check` - run mypy in strict mode
- `make format` - run Ruff formatter
- `make build` - build sdist and wheel
- `make lang` - run textlint for prose/docs
- `make super-linter` - run super-linter via Docker

For Python changes, run:

```sh
make test && make lint && make type-check && make super-linter
```

For documentation changes, run:

```sh
make lang
```

## Code conventions

- Target Python **3.12**.
- Keep type hints complete; mypy runs in **strict** mode.
- Prefer small dataclasses and pure functions over hidden state.
- Keep CLI parsing in `cli.py` thin. Put behavior in the module that owns it.
- Keep `install.py` focused on orchestration. Put low-level file management in `managed_files.py`.
- Match the existing style: simple functions, explicit branching, no unnecessary abstraction.
- Reuse shared helpers for local and remote package-file loading instead of duplicating extraction logic.
- Remove compatibility-only helpers once callers and tests are updated.

## Behavior invariants

When changing code, preserve these unless the task explicitly changes them:

### Manifest parsing

- `ghwm.yml` must be a YAML mapping with a `workflows` list.
- Workflow entries may be strings (`linter@1.2.3`) or objects (`{name, version, target, update-triggers, update-config-files}`).
- Duplicate workflow names are rejected.
- A `/` in the suffix after `@` means it is treated as part of the name, not as a version.
- Remote installs must specify an explicit version in `ghwm.yml`.
- `source` must be in `owner/repository` form, and the owner becomes the npm scope
  (`owner/ghwm-registry` -> `@owner/ghwm-<name>`).
- `update-triggers` and `update-config-files` are per-workflow booleans.
- There is no registry switch and no legacy archive-mode manifest behavior.

### Downloading

- `--local` bypasses network download and reads from a local registry checkout.
- Remote download uses GitHub Packages npm tarballs, not repository archives.
- Auth lookup order is: `gh auth token` -> `GH_TOKEN` -> `GITHUB_TOKEN`.
- A package must contain `package/workflow.yml`, and that manifest must contain a `files` list.
- Local package reads come from `workflows/<name>/workflow.yml` and the files it declares.

### Installing

- Workflow files go to `.github/workflows/` unless `target` overrides the filename.
- Generated workflow files must keep the four-line managed header format.
- Packaged config files are written as-is with no managed header.
- Unmanaged files are skipped unless `--force`.
- Already up-to-date managed files are skipped.
- On workflow update, preserve the existing `on:` section by default.
- `update-triggers: true` or `--update-triggers` replaces the existing `on:` section with the packaged one.
- On first install, config files are created only when missing.
- On update, `update-config-files: false` leaves config files untouched.
- On update, `update-config-files: true` overwrites packaged config files.
- `install` prunes stale workflows by default.
- `update` re-installs without pruning.
- Prune removes workflow files only; config files are left in place.
- Modified managed workflow files are not pruned unless `--force`.
- Hashes for managed workflow files must be computed from the normalized content that is
  actually written to disk.

### Lockfile

- Lockfile filename is `ghwm.lock`.
- The schema uses `lockfileVersion` plus a `packages` array.
- Lockfile v1 entries store `name`, `version`, `source`, and `files`.
- Each tracked file stores `target`, `source_hash`, and optional `overwrite`.
- Older lockfiles are rejected with a regenerate message; do not preserve legacy tarball compatibility.
- Delete the lockfile when no packages remain.

### Auditing

- `audit` command runs static security analysis using `zizmor` on managed workflows.
- It scans only workflow targets under `.github/workflows/` (non-workflow files or custom config targets are skipped).
- It reads `ghwm.lock` to find managed files; if the lockfile is missing, it exits with `1`.
- If no managed workflows are found in the lockfile, it prints a message and exits with `0`.
- Ignored findings are excluded from the results.
- The Security Score is calculated on a logarithmic scale (exponential decay) to ensure the score never goes negative: `round(100 * exp(-deductions / 100))`, where deductions are High (20), Medium (10), Low (5), Informational (1).
- It exits with code `1` if any High or Medium findings are reported, or if the tool fails to run.

## Testing guidance

- Add or update tests in the module-aligned file under `tests/`.
- Structure tests with the Arrange / Act / Assert pattern.
- Name tests as `test_<feature>_should_<expected_behavior>_when_<state_under_test>`.
- Prefer `tmp_path` fixtures and local fake registry trees over real network access.
- Mock `gh`/HTTP download edges instead of hitting GitHub.
- Add negative-path coverage when changing package parsing, file extraction, or prune behavior.
- Cover both the happy path and meaningful edge cases for trigger preservation and config overwrite behavior.
- If you change manifest semantics, update `tests/test_manifest.py`.
- If you change install/prune/header behavior, update `tests/test_install.py`.
- If you change user-facing command behavior or output, update `tests/test_cli.py`.
- If you change download orchestration behavior, update `tests/test_download.py`.
- If you change tarball/package parsing behavior, update `tests/test_download_npm.py`.
- If you change lockfile semantics, update `tests/test_lock.py`.

## Documentation guidance

- Update `README.md` for user-facing CLI behavior, flags, or workflow examples, and call it the readme in prose.
- Update `docs/ARCHITECTURE.md` for lifecycle, module-boundary, or data-flow changes.
- If you change the managed header, package manifest semantics, or lockfile shape, update both the readme and the architecture docs.

## Useful manual smoke test

For install-flow changes, a good manual check is:

```sh
ghwm install --local ../ghwm-registry
```

Run it from a consumer repository that has a versioned `ghwm.yml` manifest.

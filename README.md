# GitHub Workflow Manager CLI

[![Lint Code Base](https://github.com/pljanicki/ghwm/actions/workflows/linter.yaml/badge.svg)](https://github.com/pljanicki/ghwm/actions/workflows/linter.yaml)
[![version](https://img.shields.io/github/v/release/pljanicki/ghwm)](https://github.com/pljanicki/ghwm/releases/latest)
[![codecov](https://codecov.io/gh/pljanicki/ghwm/graph/badge.svg)](https://codecov.io/gh/pljanicki/ghwm)
[![Python](https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white)](https://www.python.org/)

| ![ghwm CLI](.github/static/readme_header.png) |
| :---------------------------------------------------: |

> Install managed GitHub workflow files from a central marketplace repository.

Workflows are sourced from [owner/ghwm-marketplace](https://github.com/owner/ghwm-marketplace).

## Install

```sh
uv tool install git+https://github.com/pljanicki/ghwm.git
```

Or pin to a specific version tag:

```sh
uv tool install git+https://github.com/pljanicki/ghwm.git@vX.Y.Z
```

## Usage

### 1. Create `ghwm.yml` in your repository root

```yaml
source: owner/ghwm-marketplace

workflows:
  - name: linter
    version: "1.0.0"
  - name: auto-assign-pr
    version: "1.0.0"
    update-triggers: true
    update-config-files: true
```

`version` is required for registry installs. The CLI resolves each workflow to a GitHub Packages npm
package named `@<source owner>/ghwm-<name>`.

If you want to override the generated workflow filename, add `target: my-review.yml` to the
workflow entry.

### 2. Install workflows

```sh
ghwm install            # installs workflows listed in ghwm.yml
ghwm install --force    # overwrites even if files were modified locally
ghwm install --no-prune # skip removal of stale workflows
ghwm install --update-triggers # replace workflow triggers with the packaged version
ghwm update             # re-downloads all workflows (respects versions)
ghwm update --prune     # also removes managed workflows no longer in ghwm.yml
ghwm update --update-triggers # replace workflow triggers with the packaged version
ghwm list               # shows workflows declared in ghwm.yml
```

Workflow files are written to `.github/workflows/` with a managed header. Additional packaged files
such as config files are written as-is. On first install, config files are only created if the target
does not already exist. On update, config files are only overwritten when
`update-config-files: true` is set for that workflow.

| File type | First install | Update | Prune |
| --- | --- | --- | --- |
| Workflow file (`.github/workflows/*`) | Install with managed header | Update in place; preserve existing `on:` by default | Remove |
| Packaged config file | Create only when missing | Overwrite only with `update-config-files: true` | Keep |

#### Managed files

Every installed workflow file starts with a header that marks it as managed:

```yaml
# Managed by ghwm (linter@0.1.4)
# Source: @owner/ghwm-linter:linter.yml
# Hash: sha256:...
# Re-run `ghwm install` to refresh this file.
```

The CLI uses this header to:

- Distinguish managed files from hand-crafted ones (unmanaged files are never
  overwritten without `--force`).
- Preserve existing `on:` rules during updates unless `update-triggers: true`
  or `--update-triggers` is used.
- Prune stale workflow files that were removed from the manifest.

Config files do not get a managed header and are never removed during prune.

Use `ghwm update --prune` when you want one command to refresh workflows that are still in
`ghwm.yml` and remove managed workflows that were deleted from the manifest. It updates
`ghwm.lock` too.

#### Lockfile

`ghwm.lock` is a JSON file that records every installed package and the files it manages:

```json
{
  "lockfileVersion": 1,
  "packages": [
    {
      "name": "auto-assign-pr",
      "version": "2.0.0",
      "source": "@owner/ghwm-auto-assign-pr",
      "files": [
        {
          "target": ".github/workflows/auto-assign-pr.yaml",
          "source_hash": "sha256:..."
        },
        {
          "target": ".github/auto_assign.yaml",
          "source_hash": "sha256:...",
          "overwrite": false
        }
      ]
    }
  ]
}
```

Commit `ghwm.lock` alongside `ghwm.yml` so CI and teammates install the exact same
workflow package set. Old tarball-era lockfiles are rejected and must be regenerated.

### Authentication

The CLI needs read access to GitHub Packages and the marketplace repository. Set one of:

```sh
export GH_TOKEN=ghp_...        # or GITHUB_TOKEN
```

The CLI prefers `GH_TOKEN`/`GITHUB_TOKEN` when they are set. Those tokens need `read:packages`
access. If you rely on the `gh` CLI instead, make sure its token can read GitHub Packages too, for
example with:

```sh
gh auth refresh -s read:packages
```

### Local Development

Point at a local checkout of the marketplace for testing:

```sh
ghwm install --local ../ghwm-marketplace
```

With `--local`, the CLI reads `workflows/<name>/workflow.yml` directly from the checkout instead of
downloading the npm package tarball.

## Development

```sh
make install          # uv sync (dev deps)
make test             # pytest
make lint             # ruff check
make format           # ruff format
make type-check       # mypy
make clean            # remove build artifacts
```

## Architecture

See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for design details.

## License

MIT

# Manifest and Lockfile Reference

This reference describes the configuration schema for `ghwm.yml` and the lockfile format for `ghwm.lock`.

---

## `ghwm.yml`

The `ghwm.yml` file is located in the root of the consumer repository. It defines which managed workflows to install, where to fetch them from, and how to manage updates.

### Top-level Keys

| Key | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `source` | string | No | `owner/ghwm-registry` | The default registry repository in `owner/repository` format. |
| `workflows` | list | Yes | — | The list of workflows to install. |

#### Example

```yaml
source: ghwfxlab/ghwm-registry

workflows:
  - name: linter
    version: "1.0.0"
  - name: auto-assign-pr
    version: "2.0.0"
    source: other-org/custom-registry
    update-triggers: true
    update-envs: true
    update-config-files: true
```

---

## Workflow Entry Syntax

Entries under the `workflows` list can be specified in two formats:

### 1. Mapping Syntax (Recommended)

Full YAML object allowing granular per-workflow configuration:

```yaml
workflows:
  - name: linter
    version: "1.2.0"
    target: code-quality.yml
    update-triggers: false
    update-envs: false
    update-config-files: false
```

### 2. Compact String Syntax

A single string in `name` or `name@version` form:

```yaml
workflows:
  - linter@1.2.0
  - release
```

> [!NOTE]
> For remote registry downloads, an explicit version is required. If omitted in string syntax (`release`), `ghwm install` will reject the entry unless running with `--local`.

---

## Workflow Entry Fields

When using the mapping syntax, the following fields are supported:

| Field | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `name` | string | Yes | — | Identifier of the workflow package in the registry. |
| `version` | string | Conditional | `null` | Target package version (SemVer). Required for remote installs. |
| `source` | string | No | Global `source` | Repository in `owner/repository` format. Overrides the global source for this specific workflow. |
| `target` | string | No | Packaged filename | Custom target path under `.github/workflows/`. |
| `update-triggers` | boolean | No | `false` | When `true`, overwrites the existing workflow `on:` trigger section on update. |
| `update-envs` | boolean | No | `false` | When `true`, overwrites the existing workflow `env:` variables section on update. |
| `update-config-files` | boolean | No | `false` | When `true`, overwrites packaged non-workflow configuration files on update. |

### Field Details

#### `name`
The package identifier within the registry.
- Must be a non-empty string.
- Each workflow name in `workflows` must be unique. Duplicate workflow names cause a manifest parse error.
- Also supports inline versions (e.g. `name: linter@1.0.0`).

#### `version`
The exact package version string to install.
- Required for remote installs from GitHub Packages.
- Remote resolution maps to `@<source-owner>/<name>@<version>`.

#### `source`
Overrides the top-level `source` registry for this individual workflow.
- Must be in `owner/repository` format.
- The owner segment is used as the npm organization scope for the package.

#### `target`
Overrides the destination filename for the installed workflow.
- By default, the workflow file retains its filename from the package and is written to `.github/workflows/<filename>`.
- Setting `target: custom-name.yml` places the workflow file at `.github/workflows/custom-name.yml`.

#### `update-triggers`
Controls whether custom modifications to workflow triggers are preserved during updates.
- `false` (default): Preserves the existing `on:` block from the local file when updating.
- `true`: Replaces the `on:` block with the trigger configuration defined in the upstream package.
- Can also be forced globally on the CLI using `--update-triggers`.

#### `update-envs`
Controls whether custom environment variables are preserved during updates.
- `false` (default): Preserves the existing `env:` block from the local file when updating.
- `true`: Replaces the `env:` block with the upstream package's `env:` block.
- Can also be forced globally on the CLI using `--update-envs`.

#### `update-config-files`
Controls the overwrite behavior of companion configuration files bundled with the workflow.
- `false` (default): Existing configuration files on disk are never overwritten during updates.
- `true`: Overwrites existing configuration files with the packaged versions.

---

## File Update Behavior Matrix

| File Type | First Install | Update (`update-*: false`) | Update (`update-*: true`) | Prune |
| :--- | :--- | :--- | :--- | :--- |
| **Workflow File** (`.github/workflows/*`) | Created with managed header | Updated in place; preserves local `on:` and `env:` | Updated in place; overwrites `on:` and `env:` | Removed if deleted from manifest |
| **Config File** (e.g. `.eslintrc.json`) | Created only if file does not exist | Untouched | Overwritten with packaged version | Never removed |

---

## Managed Header Format

Every workflow file installed by `ghwm` prepends a four-line managed header:

```yaml
# Managed by ghwm (<name>@<version>)
# Source: @<org>/<name>:<source-file>
# Hash: sha256:<hex>
# Re-run `ghwm install` to refresh this file.
```

- **Header Lines**:
  1. Tool identifier and pinned version.
  2. Provenance link indicating npm package scope and source file path.
  3. `sha256` checksum computed from the normalized workflow body content.
  4. Refresh instruction.
- **Unmanaged Protection**: Files in `.github/workflows/` lacking this header are treated as user files and will never be overwritten or pruned without `--force`.

---

## `ghwm.lock`

The lockfile records resolved package versions, file destinations, and content hashes. It guarantees deterministic installations across environments.

Commit `ghwm.lock` alongside `ghwm.yml` in source control.

### Lockfile Schema (Version 1)

```json
{
  "lockfileVersion": 1,
  "packages": [
    {
      "name": "auto-assign-pr",
      "version": "2.0.0",
      "source": "@owner/auto-assign-pr",
      "files": [
        {
          "target": ".github/workflows/auto-assign-pr.yaml",
          "source_hash": "sha256:5a0e5ccd00cd8e850e1068707e042339e182190eb89f8a300f58c18f53876059"
        },
        {
          "target": ".github/auto_assign.yaml",
          "source_hash": "sha256:caa9a086baaf9e0f7cd71f64edfa83da6821c05e826b083221f3d02e3d6a1905",
          "overwrite": false
        }
      ]
    }
  ]
}
```

### Package Entry Fields

| Field | Type | Description |
| :--- | :--- | :--- |
| `name` | string | Workflow identifier matching the manifest entry. |
| `version` | string | Pinned package version. |
| `source` | string | Scoped npm package identifier (`@<owner>/<name>`). |
| `files` | array | List of files installed and tracked for this package. |

### File Entry Fields

| Field | Type | Description |
| :--- | :--- | :--- |
| `target` | string | Relative file path in the consumer repository. |
| `source_hash` | string | `sha256` checksum of the normalized content written to disk. |
| `overwrite` | boolean | Set to `false` when a config file must be preserved on update. |

# Contributing to GitHub Workflow Manager CLI (ghwm)

Thank you for your interest in contributing to `ghwm`! This document provides guidelines and instructions to help you set up your local development environment, run quality checks, write tests, and submit your contributions.

Before you begin, please read the [Architecture Documentation](docs/ARCHITECTURE.md) and the [AI/Developer Agent Guide](AGENTS.md) to understand the codebase structure, design principles, and invariants. Automated developer agents can also find pre-configured coding and testing standards under [.agents/skills/](.agents/skills/).

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Prerequisites](#prerequisites)
- [Development Setup](#development-setup)
- [Development Workflow](#development-workflow)
  - [Syncing Dependencies](#syncing-dependencies)
  - [Linting and Formatting](#linting-and-formatting)
  - [Type Checking](#type-checking)
  - [Running Tests](#running-tests)
  - [Documentation Linting](#documentation-linting)
  - [Pre-commit Hooks](#pre-commit-hooks)
  - [Super-Linter (Docker-based)](#super-linter-docker-based)
- [Coding Standards](#coding-standards)
- [Testing Standards](#testing-standards)
- [Pull Request Process](#pull-request-process)
  - [Branching Conventions](#branching-conventions)
  - [Commit Message Guidelines](#commit-message-guidelines)
  - [Submission Checklist](#submission-checklist)

---

## Code of Conduct

By participating in this project, you agree to maintain a respectful, welcoming, and inclusive environment. Please report any unacceptable behavior to the project maintainers.

## Prerequisites

To build and run `ghwm` locally, ensure you have the following tools installed:

1. **Python 3.12 or 3.14**: Python 3.12 is the primary target version, while Python 3.14 is used in some testing setups.
2. **[uv](https://docs.astral.sh/uv/)**: A fast Python package installer and resolver.
3. **Node.js & npx**: Required for prose and style linting on documentation files.
4. **Docker** (Optional): Required for running the repository's container-based super-linter checks.

---

## Development Setup

1. **Clone the Repository**:

   ```sh
   git clone https://github.com/ghwfxlab/ghwm.git
   cd ghwm
   ```

2. **Set Up Python Dependencies**:
   Initialize a virtual environment and sync dependencies using `uv` via the provided [Makefile](Makefile):

   ```sh
   make install
   ```

3. **Install Pre-commit Hooks**:
   Enable automated code quality checks before each commit:

   ```sh
   make setup-precommit
   ```

---

## Development Workflow

We use [Makefile](Makefile) targets to orchestrate common development tasks.

### Syncing Dependencies

Whenever dependencies are added or updated in [pyproject.toml](pyproject.toml), re-sync your virtual environment:

```sh
make install
```

*(Alternatively, run `uv sync` directly.)*

### Linting and Formatting

We use **Ruff** for linting and formatting. Run these targets frequently to keep the codebase clean:

- **Lint Check**:

  ```sh
  make lint
  ```

- **Code Formatter**:

  ```sh
  make format
  ```

### Type Checking

The codebase uses static typing extensively, and **mypy** is configured to run in **strict** mode. Ensure all your changes have full type hints:

```sh
make type-check
```

### Running Tests

We use **pytest** and **pytest-cov** to run unit and integration tests under the [tests/](tests) directory.

- **Run Tests**:

  ```sh
  make test
  ```

All tests must pass, and code coverage should be kept high (aim for 95%+).

### Documentation Linting

We use **textlint** to ensure consistency in prose and documentation files. Check Markdown documentation style using:

```sh
make lang
```

To automatically fix common prose and style warnings:

```sh
make lang-fix
```

### Pre-commit Hooks

To run the full suite of pre-commit hooks manually against all files:

```sh
make precommit
```

### Super-Linter (Docker-based)

To replicate the full CI environment locally, run **super-linter** using Docker:

- **Run Super-Linter**:

  ```sh
  make super-linter
  ```

- **Run Super-Linter and autofix**:

  ```sh
  make super-linter-fix
  ```

---

## Coding Standards

Please adhere to the following design patterns and styling guidelines:

- **Simplicity & Clarity**: Prefer small, focused dataclasses and pure functions. Minimize complex class hierarchies or hidden state.
- **Explicit Branching**: Write explicit, readable control flows. Avoid clever tricks or overly generic abstractions.
- **Separation of Concerns**:
  - Keep CLI arguments and command orchestration in [src/ghwm/cli.py](src/ghwm/cli.py).
  - Put low-level workflow/config file interactions in [src/ghwm/managed_files.py](src/ghwm/managed_files.py).
  - Put high-level installation and pruning steps in [src/ghwm/install.py](src/ghwm/install.py).
- **Documentation**: If you change any public behavior, flags, or manifest file formats, document them in [README.md](README.md) and update [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) where relevant.

---

## Testing Standards

All tests are placed in the [tests/](tests) directory and follow these rules:

- **Arrange / Act / Assert**: Structure your test logic using the AAA pattern.
- **Naming Conventions**: Use descriptive test names in the following format:
  `test_<feature>_should_<expected_behavior>_when_<state_under_test>`
- **No Real Network Calls**: Mock all network boundaries (GitHub Packages registry requests, API calls). Use pytest's `tmp_path` fixture and local fake filesystem structures to mock file-loading or remote checkouts.
- **File Alignment**: Write tests in the test file corresponding to the module name (e.g., test changes in `src/ghwm/install.py` in `tests/test_install.py`).
- **Edge Cases**: Include testing for failure paths (e.g., invalid manifests, path traversal attempts, missing lockfiles, auth errors).

---

## Pull Request Process

### Branching Conventions

Name your branches to indicate the purpose of your changes:

- `feat/description` — New features (e.g., `feat/add-audit-command`)
- `fix/description` — bugfixes (e.g., `fix/path-traversal-leak`)
- `docs/description` — Documentation improvements (e.g., `docs/add-contributing-guide`)
- `chore/description` — CI updates, dependencies, refactorings (e.g., `chore/bump-actions`)

### Commit Message Guidelines

Keep commit messages concise and descriptive. Use conventional commit prefixes:

- `feat: add audit command to scan managed workflows using zizmor`
- `fix: correct path resolution when handling custom target files`
- `chore: update dependabot configurations`
- `docs: update architecture with security auditing lifecycle`

### Submission Checklist

Before submitting a Pull Request, run this script to ensure all local checks pass:

```sh
# Run python tests, linting, and type-checks
make test && make lint && make type-check

# Run documentation style checks
make lang
```

Verify that:

1. All unit tests pass.
2. Mypy reports no strict type-checking issues.
3. Ruff reports no linting or formatting violations.
4. No textlint issues remain in Markdown files.
5. `git status` lists only the intended files.

---
name: python-coding-standards
description: "Reusable Python coding standards for implementation, refactoring, and review work. Use whenever writing or reviewing Python code, especially when you need guidance on typing, error handling, subprocess safety, module boundaries, or matching an existing codebase. Follow repository-specific instructions and existing project tooling when they are available."
---

# python-coding-standards

Use this skill as the generic baseline for Python work. Repository-specific rules may live in project instructions, `README.md`, `Makefile`, `pyproject.toml`, or CI config, so check those sources first when they are available.

## Compatibility

- Best for Python repositories with an existing formatter, linter, type checker, and test workflow.
- Works whether repository instructions live in dedicated instruction files, other docs, or only in project tooling.
- Safe to use as a standalone baseline when no repository-specific instructions are present.

## Start with repository context

1. Read repository-specific instructions if present.
2. Inspect `pyproject.toml`, `Makefile`, CI config, and the nearest existing implementation before changing code.
3. Match the repository's existing structure and naming unless the task explicitly requires a broader refactor.

## Core principles

- Prefer small, readable functions over clever or heavily abstracted code.
- Keep changes surgical; do not refactor unrelated areas.
- Reuse existing helpers before introducing new ones.
- Keep types explicit enough for the repository's configured type checker.
- Prefer descriptive local names for collections and loop items; avoid one-letter iteration variables unless a conventional index like `i` is clearly the most readable choice.
- Write error messages for operators and maintainers, not just for the current task.
- Add comments only when a block would otherwise be hard to understand.

## Error handling

- Do not add bare `except:` blocks.
- Catch only exceptions you can handle meaningfully.
- Prefer `except SomeError as exc` over `as e`.
- Do not silently swallow failures or return success-shaped defaults for unexpected errors.
- When falling back between values, be careful not to discard valid falsy values like `0`, `False`, `""`, or `[]`.

## Tooling

- Use the repository's existing formatter, linter, type checker, and test runner.
- Do not introduce new tooling when the repository already has established commands.
- When changing dependencies, follow the repository's existing dependency-management workflow.

## Module boundaries

- Do not import another module's private names.
- Keep entrypoints thin; move durable behavior into the owning module.
- Extract shared helpers only when reuse is real, not speculative.
- Remove duplicate helpers if a clear canonical implementation already exists.
- Keep constants in one place when they are shared across multiple functions or modules.

## Security and robustness

- Do not use `subprocess` with `shell=True` for untrusted input.
- Prefer argument lists to constructed shell strings.
- Use safe `tempfile` helpers instead of manual temp path creation.
- Do not log secrets, credentials, or full sensitive payloads.
- Treat archives, XML, and external data as untrusted input.
- Avoid code paths that depend on wall-clock timing, global mutable state, or ambient environment when a dependency can be injected instead.

## Code review guidance

When reviewing Python changes, focus on:

1. Correctness and unintended behavior changes
2. Type safety and data-shape clarity
3. Error handling and observability
4. Duplicate logic or unnecessary abstraction
5. Unsafe subprocess, file, tempdir, or parsing behavior
6. Missing or weak tests for changed behavior

## File-specific guidance

- `.py`: follow nearby module patterns, keep imports tidy, and keep public interfaces explicit.
- Tests: follow the repository's existing test style and helpers.
- Documentation: update the readme or architecture docs when behavior changes, following repository-specific documentation rules when they exist.

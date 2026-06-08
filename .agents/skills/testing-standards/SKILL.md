---
name: testing-standards
description: "Reusable test-writing and test-review guidance for Python repositories. Use whenever adding, updating, or reviewing tests, debugging test failures, or deciding how to validate a Python change. Follow repository-specific instructions and existing project tooling when they are available for the repository's actual test commands, markers, and required suites."
---

# testing-standards

Use this skill as the generic baseline for tests. Repository-specific commands, markers, required suites, and naming/style rules may live in project instructions, `README.md`, `Makefile`, `pyproject.toml`, or CI config.

## Compatibility

- Best for Python repositories that already have an established test runner and local test patterns.
- Works whether repository-specific guidance lives in dedicated instruction files, other docs, or only in project tooling.
- Safe to use as a standalone baseline when no repository-specific testing guide is present.

## Start with repository context

1. Read repository-specific instructions if present.
2. Inspect the existing `tests/` layout and nearby test files before writing new tests.
3. Use the repository's existing test commands instead of inventing new entrypoints.
4. If the repository defines a required naming convention or structure, follow it exactly.

## Test design principles

- Add or update tests for the behavior you changed.
- Prefer focused tests that make one behavior obvious.
- Keep tests deterministic and independent.
- Use the simplest level of test that gives confidence.
- Prefer local fixtures, temp directories, and mocks over network or service dependencies unless the repository already expects broader integration tests.

## Recommended structure

- Use the Arrange / Act / Assert pattern.
- Keep setup close to the assertions unless shared fixtures materially reduce duplication.
- If the repository does not define a stricter rule elsewhere, prefer test names in the form `test_<feature>_should_<expected_behavior>_when_<state_under_test>`.
- Prefer descriptive variable names in tests, including loop variables and values derived during setup; avoid one-letter iteration variables unless a conventional index is genuinely clearer.
- Reuse existing factories, fixtures, and helper utilities before adding new ones.

## What to cover

- Happy path behavior
- Important validation or error paths
- Regression cases for reported bugs
- User-visible behavior changes
- Boundary cases when the logic is branchy or stateful

## Isolation guidance

- Do not make real network calls in fast tests unless the repository already relies on them.
- Prefer `tmp_path`, temporary directories, or in-memory data over persistent filesystem state.
- Mock external processes, HTTP calls, and time where needed for determinism.
- Avoid over-mocking internal logic when an in-process test would be clearer and safer.

## Async and framework guidance

- Follow the repository's existing async test approach and plugins.
- Follow the repository's existing marker conventions if it has them.
- Do not introduce a new test framework or marker taxonomy unless the task explicitly requires it.

## Maintenance rules

- Remove or rewrite tests when the production behavior they covered is removed or renamed.
- Keep shared helpers in stable locations such as fixtures modules or `conftest.py` when the repository already uses them.
- Do not leave dead tests, dead fixtures, or stale assertions behind after a change.

## Test review guidance

When reviewing tests, check:

1. Does each test prove behavior that matters?
2. Are assertions specific enough to catch regressions?
3. Is the test isolated from flaky external state?
4. Does the setup reflect the repository's existing style?
5. Are there missing tests for changed failure paths or regressions?

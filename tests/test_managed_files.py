import pytest

from ghwm.managed_files import _preserve_existing_envs, _preserve_existing_triggers


def _workflow(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def test_preserve_existing_envs_should_raise_value_error_when_yaml_is_not_mapping() -> None:
    with pytest.raises(ValueError, match=r"Workflow YAML must be a mapping to preserve env configuration\."):
        _preserve_existing_envs("- list item", "name: v2\nenv:\n  MY_VAR: new\n")

    with pytest.raises(ValueError, match=r"Workflow YAML must be a mapping to preserve env configuration\."):
        _preserve_existing_envs("name: v1\nenv:\n  MY_VAR: old\n", "- list item")


def test_preserve_existing_envs_should_return_new_content_when_envs_are_equal() -> None:
    existing = "name: v1\nenv:\n  MY_VAR: same\n"
    new = "name: v2\nenv:\n  MY_VAR: same\n"

    result = _preserve_existing_envs(existing, new)
    assert result == new


def test_preserve_existing_envs_should_preserve_packaged_workflow_formatting_when_values_differ() -> None:
    existing = _workflow(
        "name: v1",
        "on: # yamllint disable-line rule:truthy",
        "  schedule:",
        "    - cron: '0 6 * * 1,3,5'",
        "env:",
        '  GHWM_VERSION: "1.3.0"',
        "jobs:",
        "  test:",
        "    runs-on: ubuntu-latest",
    )
    new = _workflow(
        "# Packaged workflow comment that should be retained",
        "name: v2",
        "on: # yamllint disable-line rule:truthy",
        "  schedule:",
        "    - cron: '0 6 * * 1,3,5'",
        "env:",
        '  GHWM_VERSION: "v1.3.0"',
        "jobs:",
        "  test:",
        "    runs-on: ubuntu-latest",
        "    steps:",
        "      - run: |",
        "          echo 'preserve this block scalar'",
    )

    result = _preserve_existing_envs(existing, new)

    assert result == _workflow(
        "# Packaged workflow comment that should be retained",
        "name: v2",
        "on: # yamllint disable-line rule:truthy",
        "  schedule:",
        "    - cron: '0 6 * * 1,3,5'",
        "env:",
        '  GHWM_VERSION: "1.3.0"',
        "jobs:",
        "  test:",
        "    runs-on: ubuntu-latest",
        "    steps:",
        "      - run: |",
        "          echo 'preserve this block scalar'",
    )


def test_preserve_existing_triggers_should_preserve_packaged_workflow_formatting_when_values_differ() -> None:
    existing = _workflow(
        "name: v1",
        "on:",
        "  push:",
        "    branches:",
        "      - release/*",
        "env:",
        "  MY_VAR: value",
    )
    new = _workflow(
        "# Packaged workflow comment",
        "name: v2",
        "on:",
        "  workflow_dispatch:",
        "env:",
        "  MY_VAR: value",
    )

    result = _preserve_existing_triggers(existing, new)

    assert result == _workflow(
        "# Packaged workflow comment",
        "name: v2",
        "on:",
        "  push:",
        "    branches:",
        "      - release/*",
        "env:",
        "  MY_VAR: value",
    )


def test_preserve_existing_triggers_should_preserve_quoted_on_key_when_values_differ() -> None:
    existing = _workflow(
        "name: v1",
        '"on":',
        "  push:",
    )
    new = _workflow(
        "name: v2",
        "on:",
        "  workflow_dispatch:",
    )

    result = _preserve_existing_triggers(existing, new)

    assert result == _workflow(
        "name: v2",
        '"on":',
        "  push:",
    )

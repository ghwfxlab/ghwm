import pytest

from ghwm.managed_files import _find_top_level_section, _preserve_existing_envs, _preserve_existing_triggers


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


def test_find_top_level_section_should_return_none_when_key_is_absent() -> None:
    assert _find_top_level_section("name: workflow\n", "env") is None


def test_preserve_existing_envs_should_raise_value_error_when_existing_key_cannot_be_located() -> None:
    existing = _workflow(
        "!!str env:",
        "  MY_VAR: consumer_changed",
    )
    new = _workflow(
        "env:",
        "  MY_VAR: package_value",
    )

    with pytest.raises(ValueError, match=r"Could not find the existing env section in the workflow YAML\."):
        _preserve_existing_envs(existing, new)


def test_preserve_existing_envs_should_append_existing_section_when_packaged_workflow_removes_it() -> None:
    existing = _workflow(
        "env:",
        "  MY_VAR: consumer_changed",
    )
    new = _workflow("name: v2")

    result = _preserve_existing_envs(existing, new)

    assert result == _workflow(
        "name: v2",
        "env:",
        "  MY_VAR: consumer_changed",
    )


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

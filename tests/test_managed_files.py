import pytest

from ghwm.managed_files import (
    _find_child_section,
    _find_top_level_section,
    _locate_job_runs_on,
    _preserve_existing_envs,
    _preserve_existing_runs_on,
    _preserve_existing_triggers,
    extract_body,
)


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


def test_extract_body_should_return_empty_string_when_content_is_empty() -> None:
    # Arrange
    content = ""

    # Act
    result = extract_body(content)

    # Assert
    assert result == ""


def test_extract_body_should_return_empty_string_when_content_has_only_comments() -> None:
    # Arrange
    content = "# header 1\n# header 2\n"

    # Act
    result = extract_body(content)

    # Assert
    assert result == ""


def test_extract_body_should_strip_header_and_preserve_workflow_body_when_header_is_present() -> None:
    # Arrange
    content = "# Managed by ghwm\n# Hash: 123\n\nname: my-workflow\n"

    # Act
    result = extract_body(content)

    # Assert
    assert result == "name: my-workflow\n"


def _jobs_workflow(*job_lines: str, header: str = "name: wf") -> str:
    return _workflow(header, "jobs:", *job_lines)


_SCRIPT_STEPS = ("    steps:", "      - run: |", "          runs-on: no")


@pytest.mark.parametrize(
    ("existing_jobs", "new_jobs", "expected_jobs"),
    [
        pytest.param(
            ("  build:", "    runs-on: self-hosted"),
            ("  build:", "    runs-on: ubuntu-latest", "    steps: []"),
            ("  build:", "    runs-on: self-hosted", "    steps: []"),
            id="scalar",
        ),
        pytest.param(
            ("  build:", "    runs-on:", "      - self-hosted", "      - linux", "    steps: []"),
            ("  build:", "    runs-on: ubuntu-latest", "    steps: []"),
            ("  build:", "    runs-on:", "      - self-hosted", "      - linux", "    steps: []"),
            id="list",
        ),
        pytest.param(
            ("  build:", "    runs-on:", "      group: big", "      labels: [gpu]", "    steps: []"),
            ("  build:", "    steps: []", "    runs-on: ubuntu-latest"),
            ("  build:", "    steps: []", "    runs-on:", "      group: big", "      labels: [gpu]"),
            id="group-and-labels-mapping",
        ),
        pytest.param(
            ("  lint:", "    runs-on: ubuntu-latest", "  test:", "    runs-on: self-hosted"),
            ("  lint:", "    runs-on: ubuntu-24.04", "  test:", "    runs-on: ubuntu-24.04"),
            ("  lint:", "    runs-on: ubuntu-latest", "  test:", "    runs-on: self-hosted"),
            id="several-jobs",
        ),
        pytest.param(
            ("  build:", "    runs-on: self-hosted"),
            ("  build:", "    runs-on: ubuntu-latest", "  extra:", "    runs-on: ubuntu-latest"),
            ("  build:", "    runs-on: self-hosted", "  extra:", "    runs-on: ubuntu-latest"),
            id="job-added-upstream-takes-packaged-value",
        ),
        pytest.param(
            ("  build:", "    runs-on: self-hosted # our runner", "    steps: []"),
            (
                "  # packaged comment",
                "  build:",
                "    # runner note",
                "    runs-on: ubuntu-latest",
                "",
                "    steps: []",
            ),
            (
                "  # packaged comment",
                "  build:",
                "    # runner note",
                "    runs-on: self-hosted # our runner",
                "",
                "    steps: []",
            ),
            id="comments",
        ),
        pytest.param(
            ("    build:", "        runs-on:", "            - self-hosted", "            - linux"),
            ("  build:", "    runs-on: ubuntu-latest"),
            ("  build:", "    runs-on:", "        - self-hosted", "        - linux"),
            id="existing-file-uses-other-indent",
        ),
        pytest.param(
            ("  build:", "    runs-on: self-hosted"),
            ("    build:", "        runs-on: ubuntu-latest"),
            ("    build:", "        runs-on: self-hosted"),
            id="existing-file-uses-smaller-indent",
        ),
        pytest.param(
            ("  build:", "    runs-on: self-hosted", *_SCRIPT_STEPS),
            ("  build:", "    runs-on: ubuntu-latest", *_SCRIPT_STEPS),
            ("  build:", "    runs-on: self-hosted", *_SCRIPT_STEPS),
            id="runs-on-text-inside-step-script-is-ignored",
        ),
    ],
)
def test_preserve_existing_runs_on_should_keep_existing_value_when_values_differ(
    existing_jobs: tuple[str, ...], new_jobs: tuple[str, ...], expected_jobs: tuple[str, ...]
) -> None:
    existing = _jobs_workflow(*existing_jobs)
    new = _jobs_workflow(*new_jobs, header="name: v2")

    result, notices = _preserve_existing_runs_on(existing, new, name="wf")

    assert result == _jobs_workflow(*expected_jobs, header="name: v2")
    assert notices == []


@pytest.mark.parametrize(
    ("existing", "new"),
    [
        pytest.param(
            _jobs_workflow("  build:", "    runs-on: ubuntu-latest"),
            _jobs_workflow("  build:", "    runs-on: ubuntu-latest", "    steps: []", header="name: v2"),
            id="values-are-equal",
        ),
        pytest.param(
            "name: v1\njobs:\n  a:\n    runs-on: x\n",
            "name: v2\n",
            id="packaged-workflow-has-no-jobs",
        ),
        pytest.param(
            _jobs_workflow("  call:", "    runs-on: self-hosted"),
            _jobs_workflow("  call:", "    uses: org/repo/.github/workflows/x.yml@v1", header="name: v2"),
            id="packaged-job-has-no-runs-on",
        ),
        pytest.param(
            _jobs_workflow("  call:", "    uses: org/repo/.github/workflows/x.yml@v1"),
            _jobs_workflow("  call:", "    runs-on: ubuntu-latest", header="name: v2"),
            id="existing-job-has-no-runs-on",
        ),
    ],
)
def test_preserve_existing_runs_on_should_return_new_content_when_there_is_nothing_to_preserve(
    existing: str, new: str
) -> None:
    result, notices = _preserve_existing_runs_on(existing, new, name="wf")

    assert result == new
    assert notices == []


def test_preserve_existing_runs_on_should_report_notice_when_preserved_job_no_longer_exists_upstream() -> None:
    existing = _jobs_workflow("  old:", "    runs-on: self-hosted", "  build:", "    runs-on: ubuntu-latest")
    new = _jobs_workflow("  build:", "    runs-on: ubuntu-latest", header="name: v2")

    result, notices = _preserve_existing_runs_on(existing, new, name="wf")

    assert result == new
    assert notices == ["wf: job 'old' no longer exists upstream; its local runs-on was not kept"]


@pytest.mark.parametrize(
    ("existing", "new"),
    [
        pytest.param("- list item", "name: v2\n", id="existing-is-not-a-mapping"),
        pytest.param("name: v1\n", "- list item", id="packaged-is-not-a-mapping"),
    ],
)
def test_preserve_existing_runs_on_should_raise_value_error_when_yaml_is_not_mapping(existing: str, new: str) -> None:
    with pytest.raises(ValueError, match=r"Workflow YAML must be a mapping to preserve runs-on configuration\."):
        _preserve_existing_runs_on(existing, new, name="wf")


def test_preserve_existing_runs_on_should_raise_value_error_when_job_is_written_in_flow_style() -> None:
    existing = "name: v1\njobs: {build: {runs-on: self-hosted}}\n"
    new = _jobs_workflow("  build:", "    runs-on: ubuntu-latest", header="name: v2")

    with pytest.raises(ValueError, match=r"Could not find the runs-on section of job 'build'"):
        _preserve_existing_runs_on(existing, new, name="wf")


def test_preserve_existing_runs_on_should_end_value_with_newline_when_existing_file_has_no_trailing_newline() -> None:
    existing = "name: wf\njobs:\n  build:\n    runs-on: self-hosted"
    new = _jobs_workflow("  build:", "    runs-on: ubuntu-latest", "    steps: []", header="name: v2")

    result, _ = _preserve_existing_runs_on(existing, new, name="wf")

    assert result == _jobs_workflow("  build:", "    runs-on: self-hosted", "    steps: []", header="name: v2")


@pytest.mark.parametrize(
    ("content", "key"),
    [
        pytest.param("jobs:", "build", id="parent-has-no-newline"),
        pytest.param("jobs: {build: {runs-on: x}}\n", "build", id="parent-has-no-indented-children"),
        pytest.param("jobs:\n  lint:\n    runs-on: x\n", "build", id="key-is-not-a-child"),
    ],
)
def test_find_child_section_should_return_none_when_key_cannot_be_located(content: str, key: str) -> None:
    assert _find_child_section(content, (0, len(content)), key) is None


@pytest.mark.parametrize(
    ("content", "job_id"),
    [
        pytest.param("name: wf\n", "build", id="no-jobs-section"),
        pytest.param(_jobs_workflow("  lint:", "    runs-on: x"), "build", id="job-is-missing"),
        pytest.param(_jobs_workflow("  build:", "    steps: []"), "build", id="job-has-no-runs-on"),
    ],
)
def test_locate_job_runs_on_should_return_none_when_runs_on_cannot_be_located(content: str, job_id: str) -> None:
    assert _locate_job_runs_on(content, job_id) is None

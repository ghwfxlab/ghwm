"""Tests for ghwm.metadata."""

from __future__ import annotations

from ghwm.metadata import extract_workflow_metadata, parse_commented_frontmatter, parse_tags


class TestParseCommentedFrontmatter:
    def test_parse_commented_frontmatter_should_extract_fields_when_delimited_by_dashes(self) -> None:
        # Arrange
        content = (
            "# ---\n"
            "# title: Super-Linter\n"
            "# description: Code linting workflow\n"
            "# tags:\n"
            "#   - lint\n"
            "#   - actions\n"
            "# icon: fact_check\n"
            "# owner: ghwfxlab\n"
            "# ---\n"
            "---\n"
            "name: super-linter\n"
        )

        # Act
        result = parse_commented_frontmatter(content)

        # Assert
        assert result["title"] == "Super-Linter"
        assert result["description"] == "Code linting workflow"
        assert result["tags"] == ["lint", "actions"]
        assert result["icon"] == "fact_check"
        assert result["owner"] == "ghwfxlab"

    def test_parse_commented_frontmatter_should_extract_fields_when_using_undelimited_top_comments(self) -> None:
        # Arrange
        content = (
            "# title: Auto Assign PR\n"
            "# description: Automatically assign reviewers\n"
            "# icon: person_add\n"
            "\n"
            "name: auto-assign-pr\n"
        )

        # Act
        result = parse_commented_frontmatter(content)

        # Assert
        assert result["title"] == "Auto Assign PR"
        assert result["description"] == "Automatically assign reviewers"
        assert result["icon"] == "person_add"

    def test_parse_commented_frontmatter_should_return_empty_dict_when_no_frontmatter_exists(self) -> None:
        # Arrange
        content = "name: simple-workflow\nfiles: []\n"

        # Act
        result = parse_commented_frontmatter(content)

        # Assert
        assert result == {}

    def test_parse_commented_frontmatter_should_extract_fields_when_delimiters_not_closed(self) -> None:
        # Arrange
        content = "# ---\n# title: Unclosed Frontmatter\n"

        # Act
        result = parse_commented_frontmatter(content)

        # Assert
        assert result["title"] == "Unclosed Frontmatter"

    def test_parse_commented_frontmatter_should_return_empty_dict_when_content_is_empty(self) -> None:
        # Arrange / Act / Assert
        assert parse_commented_frontmatter("") == {}

    def test_parse_commented_frontmatter_should_return_empty_dict_when_yaml_is_malformed(self) -> None:
        # Arrange
        content = "# ---\n# [invalid: yaml: : foo\n# ---\n"

        # Act
        result = parse_commented_frontmatter(content)

        # Assert
        assert result == {}


class TestParseTags:
    def test_parse_tags_should_return_list_when_input_is_a_list(self) -> None:
        # Arrange / Act
        result = parse_tags(["lint", "actions", "pre-commit"])

        # Assert
        assert result == ["lint", "actions", "pre-commit"]

    def test_parse_tags_should_split_comma_separated_string(self) -> None:
        # Arrange / Act
        result = parse_tags("lint, actions, pre-commit")

        # Assert
        assert result == ["lint", "actions", "pre-commit"]

    def test_parse_tags_should_parse_json_array_string(self) -> None:
        # Arrange / Act
        result = parse_tags('["lint", "actions"]')

        # Assert
        assert result == ["lint", "actions"]

    def test_parse_tags_should_return_empty_list_when_input_is_none_or_empty(self) -> None:
        # Arrange / Act / Assert
        assert parse_tags(None) == []
        assert parse_tags("") == []
        assert parse_tags([]) == []

    def test_parse_tags_should_cap_at_twenty_tags(self) -> None:
        # Arrange
        many_tags = [f"tag-{i}" for i in range(25)]

        # Act
        result = parse_tags(many_tags)

        # Assert
        assert len(result) == 20


class TestExtractWorkflowMetadata:
    def test_extract_workflow_metadata_should_return_full_metadata_when_frontmatter_is_present(self) -> None:
        # Arrange
        workflow_yml = (
            "# ---\n"
            "# title: Super-Linter\n"
            "# description: Linting workflow\n"
            "# tags:\n"
            "#   - lint\n"
            "# icon: fact_check\n"
            "# owner: custom-org\n"
            "# ---\n"
            "name: super-linter\n"
        )

        # Act
        meta = extract_workflow_metadata(
            workflow_name="super-linter",
            source="ghwfxlab/ghwm-registry",
            version="1.0.1",
            workflow_yml_content=workflow_yml,
        )

        # Assert
        assert meta["title"] == "Super-Linter"
        assert meta["description"] == "Linting workflow"
        assert meta["tags"] == ["lint"]
        assert meta["icon"] == "fact_check"
        assert meta["owner"] == "custom-org"
        assert meta["version"] == "1.0.1"
        assert meta["source"] == "ghwfxlab/ghwm-registry"

    def test_extract_workflow_metadata_should_fallback_to_package_json_when_frontmatter_omits_fields(
        self,
    ) -> None:
        # Arrange
        pkg_json = '{"name": "@ghwfxlab/ghwm-linter", "version": "2.0.0", "description": "From package.json"}'

        # Act
        meta = extract_workflow_metadata(
            workflow_name="linter",
            source="ghwfxlab/ghwm-registry",
            package_json_content=pkg_json,
        )

        # Assert
        assert meta["title"] is None
        assert meta["description"] == "From package.json"
        assert meta["version"] == "2.0.0"
        assert meta["owner"] == "ghwfxlab"
        assert meta["tags"] == []

    def test_extract_workflow_metadata_should_fallback_to_repo_info_when_package_lacks_metadata(self) -> None:
        # Arrange
        repo_info = {
            "description": "Community action workflows",
            "topics": ["actions", "automation"],
        }

        # Act
        meta = extract_workflow_metadata(
            workflow_name="example",
            source="google-github-actions/example-workflows",
            version="0.1.0",
            repo_info=repo_info,
        )

        # Assert
        assert meta["description"] == "Community action workflows"
        assert meta["tags"] == ["actions", "automation"]
        assert meta["owner"] == "google-github-actions"

    def test_extract_workflow_metadata_should_safely_handle_completely_empty_sources(self) -> None:
        # Arrange / Act
        meta = extract_workflow_metadata(
            workflow_name="minimal",
            source="owner/repo",
            version="1.0.0",
        )

        # Assert
        assert meta == {
            "title": None,
            "description": None,
            "tags": [],
            "icon": None,
            "version": "1.0.0",
            "owner": "owner",
            "source": "owner/repo",
        }

    def test_extract_workflow_metadata_should_use_workflow_file_content_when_workflow_yml_lacks_frontmatter(
        self,
    ) -> None:
        # Arrange
        workflow_yml = "name: my-flow\nfiles:\n  - source: main.yml\n    target: .github/workflows/main.yml\n"
        main_yml = "# ---\n# title: Main Flow\n# description: Main pipeline\n# ---\nname: main\n"

        # Act
        meta = extract_workflow_metadata(
            workflow_name="my-flow",
            source="owner/repo",
            version="1.0.0",
            workflow_yml_content=workflow_yml,
            workflow_file_content=main_yml,
        )

        # Assert
        assert meta["title"] == "Main Flow"
        assert meta["description"] == "Main pipeline"

    def test_extract_workflow_metadata_should_read_manifest_keys_and_created_at(self) -> None:
        # Arrange
        frontmatter = "# ---\n# createdAt: '2026-09-08T12:00:00Z'\n# ---\nname: flow\n"
        manifest_data = {
            "title": "Manifest Title",
            "icon": "verified",
            "tags": ["ci", "cd"],
        }

        # Act
        meta = extract_workflow_metadata(
            workflow_name="flow",
            source="owner/repo",
            workflow_yml_content=frontmatter,
            manifest_data=manifest_data,
        )

        # Assert
        assert meta["title"] == "Manifest Title"
        assert meta["icon"] == "verified"
        assert meta["tags"] == ["ci", "cd"]
        assert meta["created_at"] == "2026-09-08T12:00:00Z"

    def test_extract_workflow_metadata_should_ignore_invalid_package_json(self) -> None:
        # Arrange / Act
        meta = extract_workflow_metadata(
            workflow_name="flow",
            source="owner/repo",
            package_json_content="not valid json",
        )

        # Assert
        assert meta["description"] is None

    def test_extract_workflow_metadata_should_ignore_package_json_when_not_a_dict(self) -> None:
        # Arrange / Act
        meta = extract_workflow_metadata(
            workflow_name="flow",
            source="owner/repo",
            package_json_content='["item1", "item2"]',
        )

        # Assert
        assert meta["description"] is None

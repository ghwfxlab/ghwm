import pytest

from ghwm.managed_files import _preserve_existing_envs

def test_preserve_existing_envs_should_raise_value_error_when_yaml_is_not_mapping() -> None:
    with pytest.raises(ValueError, match="Workflow YAML must be a mapping to preserve env configuration."):
        _preserve_existing_envs("- list item", "name: v2\nenv:\n  MY_VAR: new\n")
    
    with pytest.raises(ValueError, match="Workflow YAML must be a mapping to preserve env configuration."):
        _preserve_existing_envs("name: v1\nenv:\n  MY_VAR: old\n", "- list item")

def test_preserve_existing_envs_should_return_new_content_when_envs_are_equal() -> None:
    existing = "name: v1\nenv:\n  MY_VAR: same\n"
    new = "name: v2\nenv:\n  MY_VAR: same\n"
    
    result = _preserve_existing_envs(existing, new)
    assert result == new

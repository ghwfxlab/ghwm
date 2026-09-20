"""Tests for ghwm.download_npm."""

from __future__ import annotations

import io
import json
import tarfile
from email.message import Message
from http import HTTPStatus
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest

from ghwm.download_npm import (
    InstalledFile,
    build_installed_files,
    download_npm_tarball,
    extract_npm_package,
    extract_tarball_metadata,
    find_primary_workflow_source,
    manifest_files,
    npm_package_metadata_url,
    npm_tarball_url,
    parse_workflow_manifest_data,
    read_workflow_manifest,
    resolve_latest_version,
)
from tests.shared import AUTO_ASSIGN_PR, LINTER

ORG = "owner"
VERSION = "1.0.0"
TOKEN = "token"
PACKAGE_NAME = f"@{ORG}/{LINTER}"
METADATA_URL = "https://npm.pkg.github.com/@owner%2Flinter"
TARBALL_URL = f"https://npm.pkg.github.com/download/{PACKAGE_NAME}/{VERSION}/hash"
MANIFEST_PATH = "package/workflow.yml"
LINTER_PACKAGE_PATH = f"package/{LINTER}.yml"
LINTER_TARGET_PATH = f".github/workflows/{LINTER}.yml"
AUTO_ASSIGN_PR_PACKAGE_PATH = f"package/{AUTO_ASSIGN_PR}.yaml"
AUTO_ASSIGN_PR_TARGET_PATH = f".github/workflows/{AUTO_ASSIGN_PR}.yaml"
CONFIG_SOURCE_PATH = "config/auto_assign.yaml"
CONFIG_PACKAGE_PATH = f"package/{CONFIG_SOURCE_PATH}"
CONFIG_TARGET_PATH = ".github/auto_assign.yaml"


def _make_tarball_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for relative_path, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=relative_path)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class _FakeResponse(io.BytesIO):
    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        pass


def _metadata_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(payload).encode("utf-8")


def _tarball_metadata(
    url: str = TARBALL_URL,
) -> bytes:
    return _metadata_bytes(
        {
            "versions": {
                VERSION: {
                    "dist": {
                        "tarball": url,
                    }
                }
            }
        }
    )


def _http_error(url: str, code: int, message: str) -> HTTPError:
    return HTTPError(
        url=url,
        code=code,
        msg=message,
        hdrs=Message(),
        fp=None,
    )


class TestNpmPackageMetadataUrl:
    def test_npm_package_metadata_url_should_build_github_packages_url_when_org_and_package_name_are_provided(
        self,
    ) -> None:
        assert npm_package_metadata_url(ORG, LINTER) == METADATA_URL


class TestNpmTarballUrl:
    def test_npm_tarball_url_should_resolve_tarball_from_package_metadata_when_metadata_contains_requested_version(
        self,
    ) -> None:
        metadata_bytes = _tarball_metadata()

        with patch("ghwm.download_npm.urlopen", return_value=_FakeResponse(metadata_bytes)):
            tarball_url = npm_tarball_url(ORG, LINTER, VERSION, TOKEN)

        assert tarball_url == TARBALL_URL

    def test_npm_tarball_url_should_raise_when_package_is_missing_from_registry(self) -> None:
        with patch(
            "ghwm.download_npm.urlopen",
            side_effect=_http_error(
                METADATA_URL,
                HTTPStatus.NOT_FOUND.value,
                HTTPStatus.NOT_FOUND.phrase,
            ),
        ):
            with pytest.raises(FileNotFoundError, match="Workflow package not found"):
                npm_tarball_url(ORG, LINTER, VERSION, TOKEN)

    def test_npm_tarball_url_should_raise_when_metadata_omits_versions(self) -> None:
        with patch("ghwm.download_npm.urlopen", return_value=_FakeResponse(_metadata_bytes({}))):
            with pytest.raises(RuntimeError, match="missing 'versions' map"):
                npm_tarball_url(ORG, LINTER, VERSION, TOKEN)

    def test_npm_tarball_url_should_raise_when_metadata_omits_tarball_url(self) -> None:
        metadata_bytes = _metadata_bytes({"versions": {VERSION: {"dist": {}}}})

        with patch("ghwm.download_npm.urlopen", return_value=_FakeResponse(metadata_bytes)):
            with pytest.raises(RuntimeError, match=r"missing dist\.tarball"):
                npm_tarball_url(ORG, LINTER, VERSION, TOKEN)

    def test_npm_tarball_url_should_reraise_unexpected_http_error_when_registry_returns_server_error(
        self,
    ) -> None:
        with patch(
            "ghwm.download_npm.urlopen",
            side_effect=_http_error(
                METADATA_URL,
                HTTPStatus.INTERNAL_SERVER_ERROR.value,
                HTTPStatus.INTERNAL_SERVER_ERROR.phrase,
            ),
        ):
            with pytest.raises(HTTPError, match="Internal Server Error"):
                npm_tarball_url(ORG, LINTER, VERSION, TOKEN)


class TestDownloadNpmTarball:
    def test_download_npm_tarball_should_include_auth_header_when_token_is_provided(self, tmp_path: Path) -> None:
        metadata_bytes = _tarball_metadata()
        tarball_bytes = _make_tarball_bytes({MANIFEST_PATH: "files: []\n"})

        with patch("ghwm.download_npm.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = [_FakeResponse(metadata_bytes), _FakeResponse(tarball_bytes)]
            download_npm_tarball(ORG, LINTER, VERSION, tmp_path, TOKEN)

        metadata_request = mock_urlopen.call_args_list[0][0][0]
        tarball_request = mock_urlopen.call_args_list[1][0][0]
        assert metadata_request.full_url == METADATA_URL
        assert metadata_request.get_header("Authorization") == f"Bearer {TOKEN}"
        assert tarball_request.full_url == TARBALL_URL
        assert tarball_request.get_header("Authorization") == f"Bearer {TOKEN}"

    def test_download_npm_tarball_should_omit_auth_header_when_token_is_absent(self, tmp_path: Path) -> None:
        metadata_bytes = _tarball_metadata()
        tarball_bytes = _make_tarball_bytes({MANIFEST_PATH: "files: []\n"})

        with patch("ghwm.download_npm.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = [_FakeResponse(metadata_bytes), _FakeResponse(tarball_bytes)]
            download_npm_tarball(ORG, LINTER, VERSION, tmp_path, None)

        metadata_request = mock_urlopen.call_args_list[0][0][0]
        tarball_request = mock_urlopen.call_args_list[1][0][0]
        assert metadata_request.get_header("Authorization") is None
        assert tarball_request.get_header("Authorization") is None

    def test_download_npm_tarball_should_raise_when_requested_version_is_missing(self, tmp_path: Path) -> None:
        metadata_bytes = _metadata_bytes({"versions": {"1.1.0": {"dist": {"tarball": "https://example.test/pkg.tgz"}}}})

        with patch("ghwm.download_npm.urlopen", return_value=_FakeResponse(metadata_bytes)):
            with pytest.raises(FileNotFoundError, match=f"{PACKAGE_NAME}@{VERSION}"):
                download_npm_tarball(ORG, LINTER, VERSION, tmp_path, TOKEN)

    def test_download_npm_tarball_should_raise_helpful_error_when_metadata_auth_fails(self, tmp_path: Path) -> None:
        with patch(
            "ghwm.download_npm.urlopen",
            side_effect=_http_error(
                METADATA_URL,
                HTTPStatus.FORBIDDEN.value,
                HTTPStatus.FORBIDDEN.phrase,
            ),
        ):
            with pytest.raises(RuntimeError, match="read:packages"):
                download_npm_tarball(ORG, LINTER, VERSION, tmp_path, TOKEN)

    def test_download_npm_tarball_should_raise_helpful_error_when_tarball_auth_fails(self, tmp_path: Path) -> None:
        with patch("ghwm.download_npm.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = [
                _FakeResponse(_tarball_metadata()),
                _http_error(
                    TARBALL_URL,
                    HTTPStatus.FORBIDDEN.value,
                    HTTPStatus.FORBIDDEN.phrase,
                ),
            ]

            with pytest.raises(RuntimeError, match="read:packages"):
                download_npm_tarball(ORG, LINTER, VERSION, tmp_path, TOKEN)

    def test_download_npm_tarball_should_raise_when_tarball_is_missing(self, tmp_path: Path) -> None:
        with patch("ghwm.download_npm.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = [
                _FakeResponse(_tarball_metadata()),
                _http_error(
                    TARBALL_URL,
                    HTTPStatus.NOT_FOUND.value,
                    HTTPStatus.NOT_FOUND.phrase,
                ),
            ]

            with pytest.raises(FileNotFoundError, match="tarball not found"):
                download_npm_tarball(ORG, LINTER, VERSION, tmp_path, TOKEN)

    def test_download_npm_tarball_should_reraise_unexpected_tarball_http_error_when_tarball_download_fails(
        self, tmp_path: Path
    ) -> None:
        with patch("ghwm.download_npm.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = [
                _FakeResponse(_tarball_metadata()),
                _http_error(
                    TARBALL_URL,
                    HTTPStatus.BAD_GATEWAY.value,
                    HTTPStatus.BAD_GATEWAY.phrase,
                ),
            ]

            with pytest.raises(HTTPError, match="Bad Gateway"):
                download_npm_tarball(ORG, LINTER, VERSION, tmp_path, TOKEN)


class TestWorkflowManifest:
    def test_read_workflow_manifest_should_load_package_manifest_when_tarball_contains_workflow_manifest(
        self, tmp_path: Path
    ) -> None:
        tarball_path = tmp_path / "package.tgz"
        tarball_path.write_bytes(
            _make_tarball_bytes(
                {
                    MANIFEST_PATH: (
                        f"name: {LINTER}\nfiles:\n  - source: {LINTER}.yml\n    target: {LINTER_TARGET_PATH}\n"
                    ),
                    LINTER_PACKAGE_PATH: f"name: {LINTER}\n",
                }
            )
        )

        manifest_data = read_workflow_manifest(tarball_path)

        assert manifest_data["name"] == LINTER

    def test_read_workflow_manifest_should_raise_when_manifest_file_is_missing(self, tmp_path: Path) -> None:
        tarball_path = tmp_path / "package.tgz"
        tarball_path.write_bytes(_make_tarball_bytes({LINTER_PACKAGE_PATH: f"name: {LINTER}\n"}))

        with pytest.raises(FileNotFoundError, match=MANIFEST_PATH):
            read_workflow_manifest(tarball_path)

    def test_read_workflow_manifest_should_raise_when_manifest_is_not_a_mapping(self, tmp_path: Path) -> None:
        tarball_path = tmp_path / "package.tgz"
        tarball_path.write_bytes(_make_tarball_bytes({MANIFEST_PATH: f"- {LINTER}\n"}))

        with pytest.raises(ValueError, match="YAML mapping"):
            read_workflow_manifest(tarball_path)

    def test_parse_workflow_manifest_data_should_raise_when_manifest_is_not_a_mapping(self) -> None:
        with pytest.raises(ValueError, match="YAML mapping"):
            parse_workflow_manifest_data(["not", "a", "mapping"])

    def test_manifest_files_should_raise_when_manifest_is_not_a_mapping(self) -> None:
        with pytest.raises(ValueError, match="YAML mapping"):
            manifest_files(["not", "a", "mapping"])

    def test_manifest_files_should_raise_when_files_list_is_missing(self) -> None:
        with pytest.raises(ValueError) as exc_info:
            manifest_files({"name": LINTER})

        assert "'files' list" in str(exc_info.value)

    def test_manifest_files_should_raise_when_file_entry_is_not_a_mapping(self) -> None:
        with pytest.raises(ValueError, match="must be a mapping"):
            manifest_files({"files": ["linter.yml"]})

    def test_manifest_files_should_raise_when_source_is_missing(self) -> None:
        with pytest.raises(ValueError, match="non-empty source"):
            manifest_files({"files": [{"target": LINTER_TARGET_PATH}]})

    def test_manifest_files_should_raise_when_target_is_missing(self) -> None:
        with pytest.raises(ValueError, match="non-empty target"):
            manifest_files({"files": [{"source": f"{LINTER}.yml"}]})

    def test_build_installed_files_should_build_files_from_callback_when_manifest_lists_packaged_files(
        self,
    ) -> None:
        files = build_installed_files(
            {"files": [{"source": f"{LINTER}.yml", "target": LINTER_TARGET_PATH}]},
            lambda source: f"content:{source}".encode(),
        )

        assert files == [
            InstalledFile(
                source=f"{LINTER}.yml",
                content=f"content:{LINTER}.yml".encode(),
                target=LINTER_TARGET_PATH,
            )
        ]


class TestExtractNpmPackage:
    def test_extract_npm_package_should_return_installed_files_when_tarball_contains_listed_package_files(
        self, tmp_path: Path
    ) -> None:
        tarball_path = tmp_path / "package.tgz"
        tarball_path.write_bytes(
            _make_tarball_bytes(
                {
                    MANIFEST_PATH: (
                        f"name: {AUTO_ASSIGN_PR}\n"
                        "files:\n"
                        f"  - source: {AUTO_ASSIGN_PR}.yaml\n"
                        f"    target: {AUTO_ASSIGN_PR_TARGET_PATH}\n"
                        f"  - source: {CONFIG_SOURCE_PATH}\n"
                        f"    target: {CONFIG_TARGET_PATH}\n"
                    ),
                    AUTO_ASSIGN_PR_PACKAGE_PATH: f"name: {AUTO_ASSIGN_PR}\n",
                    CONFIG_PACKAGE_PATH: "addReviewers: false\n",
                }
            )
        )
        manifest_data = read_workflow_manifest(tarball_path)

        files = extract_npm_package(tarball_path, manifest_data)

        assert files == [
            InstalledFile(
                source=f"{AUTO_ASSIGN_PR}.yaml",
                content=f"name: {AUTO_ASSIGN_PR}\n".encode(),
                target=AUTO_ASSIGN_PR_TARGET_PATH,
            ),
            InstalledFile(
                source=CONFIG_SOURCE_PATH,
                content=b"addReviewers: false\n",
                target=CONFIG_TARGET_PATH,
            ),
        ]

    def test_extract_npm_package_should_raise_when_listed_file_is_missing(self, tmp_path: Path) -> None:
        tarball_path = tmp_path / "package.tgz"
        tarball_path.write_bytes(
            _make_tarball_bytes(
                {
                    MANIFEST_PATH: ("files:\n  - source: missing.yml\n    target: .github/workflows/missing.yml\n"),
                }
            )
        )
        manifest_data = read_workflow_manifest(tarball_path)

        with pytest.raises(FileNotFoundError, match=r"package/missing\.yml"):
            extract_npm_package(tarball_path, manifest_data)

    def test_extract_npm_package_should_raise_when_tar_member_cannot_be_extracted(self, tmp_path: Path) -> None:
        tarball_path = tmp_path / "package.tgz"
        tarball_path.write_bytes(b"placeholder")

        tar_context = MagicMock()
        tar_context.__enter__.return_value = tar_context
        tar_context.__exit__.return_value = None
        tar_context.getmember.return_value = object()
        tar_context.extractfile.return_value = None

        with patch("ghwm.download_npm.tarfile.open", return_value=tar_context):
            with pytest.raises(FileNotFoundError, match=MANIFEST_PATH):
                read_workflow_manifest(tarball_path)


class TestResolveLatestVersion:
    @patch("ghwm.download_npm.urlopen")
    def test_resolve_latest_version_should_return_version_and_githead_when_metadata_is_valid(
        self, mock_urlopen: MagicMock
    ) -> None:
        # Arrange
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps(
            {"dist-tags": {"latest": "1.2.3"}, "versions": {"1.2.3": {"gitHead": "abcdef"}}}
        ).encode("utf-8")
        mock_urlopen.return_value = mock_response

        # Act
        semver, githead = resolve_latest_version("owner", "linter", "token")

        # Assert
        assert semver == "1.2.3"
        assert githead == "abcdef"

    @patch("ghwm.download_npm.urlopen")
    def test_resolve_latest_version_should_raise_file_not_found_when_http_status_is_not_found(
        self, mock_urlopen: MagicMock
    ) -> None:
        # Arrange
        mock_urlopen.side_effect = HTTPError("url", HTTPStatus.NOT_FOUND, "Not Found", Message(), None)

        # Act / Assert
        with pytest.raises(FileNotFoundError, match="not found in GitHub Packages"):
            resolve_latest_version("owner", "linter", "token")

    @patch("ghwm.download_npm.urlopen")
    def test_resolve_latest_version_should_raise_runtime_error_when_dist_tags_map_is_missing(
        self, mock_urlopen: MagicMock
    ) -> None:
        # Arrange
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({"versions": {}}).encode("utf-8")
        mock_urlopen.return_value = mock_response

        # Act / Assert
        with pytest.raises(RuntimeError, match="missing 'dist-tags' map"):
            resolve_latest_version("owner", "linter", "token")

    @patch("ghwm.download_npm.urlopen")
    def test_resolve_latest_version_should_raise_runtime_error_when_latest_dist_tag_is_missing(
        self, mock_urlopen: MagicMock
    ) -> None:
        # Arrange
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({"dist-tags": {}}).encode("utf-8")
        mock_urlopen.return_value = mock_response

        # Act / Assert
        with pytest.raises(RuntimeError, match=r"missing dist-tags\.latest"):
            resolve_latest_version("owner", "linter", "token")

    @patch("ghwm.download_npm.urlopen")
    def test_resolve_latest_version_should_raise_runtime_error_when_versions_map_is_missing(
        self, mock_urlopen: MagicMock
    ) -> None:
        # Arrange
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({"dist-tags": {"latest": "1.0.0"}}).encode("utf-8")
        mock_urlopen.return_value = mock_response

        # Act / Assert
        with pytest.raises(RuntimeError, match="missing 'versions' map"):
            resolve_latest_version("owner", "linter", "token")

    @patch("ghwm.download_npm.urlopen")
    def test_resolve_latest_version_should_raise_file_not_found_when_package_version_is_missing(
        self, mock_urlopen: MagicMock
    ) -> None:
        # Arrange
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps({"dist-tags": {"latest": "1.0.0"}, "versions": {}}).encode("utf-8")
        mock_urlopen.return_value = mock_response

        # Act / Assert
        with pytest.raises(FileNotFoundError, match="Workflow package version not found"):
            resolve_latest_version("owner", "linter", "token")

    @patch("ghwm.download_npm.urlopen")
    def test_resolve_latest_version_should_raise_runtime_error_when_githead_is_missing(
        self, mock_urlopen: MagicMock
    ) -> None:
        # Arrange
        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.read.return_value = json.dumps(
            {"dist-tags": {"latest": "1.0.0"}, "versions": {"1.0.0": {}}}
        ).encode("utf-8")
        mock_urlopen.return_value = mock_response

        # Act / Assert
        with pytest.raises(RuntimeError, match="missing gitHead"):
            resolve_latest_version("owner", "linter", "token")

    @patch("ghwm.download_npm.urlopen")
    def test_resolve_latest_version_should_raise_runtime_error_when_http_status_is_unauthorized(
        self, mock_urlopen: MagicMock
    ) -> None:
        # Arrange
        mock_urlopen.side_effect = HTTPError("url", HTTPStatus.UNAUTHORIZED, "Unauthorized", Message(), None)

        # Act / Assert
        with pytest.raises(RuntimeError):
            resolve_latest_version("owner", "linter", "token")

    @patch("ghwm.download_npm.urlopen")
    def test_resolve_latest_version_should_raise_http_error_when_http_status_is_server_error(
        self, mock_urlopen: MagicMock
    ) -> None:
        # Arrange
        mock_urlopen.side_effect = HTTPError("url", HTTPStatus.INTERNAL_SERVER_ERROR, "Server Error", Message(), None)

        # Act / Assert
        with pytest.raises(HTTPError):
            resolve_latest_version("owner", "linter", "token")


class TestExtractTarballMetadata:
    def test_extract_tarball_metadata_should_extract_frontmatter_when_tarball_contains_manifest_and_frontmatter(
        self, tmp_path: Path
    ) -> None:
        # Arrange
        tarball_path = tmp_path / "package.tgz"
        tarball_bytes = _make_tarball_bytes(
            {
                "package/workflow.yml": (
                    "# ---\n"
                    "# title: Super Linter\n"
                    "# description: Lint all files\n"
                    "# tags:\n"
                    "#   - lint\n"
                    "#   - ci\n"
                    "# icon: fact_check\n"
                    "# owner: ghwfxlab\n"
                    "# ---\n"
                    "name: linter\n"
                    "files:\n"
                    "  - source: linter.yaml\n"
                    "    target: .github/workflows/linter.yaml\n"
                ),
                "package/package.json": '{"name": "@ghwfxlab/ghwm-linter", "version": "1.0.1"}',
            }
        )
        tarball_path.write_bytes(tarball_bytes)

        # Act
        meta = extract_tarball_metadata(
            tarball_path=tarball_path,
            source="ghwfxlab/ghwm-registry",
            version="1.0.1",
            manifest_data={"files": [{"source": "linter.yaml", "target": ".github/workflows/linter.yaml"}]},
        )

        # Assert
        assert meta["title"] == "Super Linter"
        assert meta["description"] == "Lint all files"
        assert meta["tags"] == ["lint", "ci"]
        assert meta["icon"] == "fact_check"
        assert meta["owner"] == "ghwfxlab"
        assert meta["version"] == "1.0.1"

    def test_extract_tarball_metadata_should_fallback_to_workflow_file_when_package_manifest_is_missing(
        self, tmp_path: Path
    ) -> None:
        # Arrange: tarball with only a workflow target file, omitting workflow.yml and package.json
        tarball_path = tmp_path / "minimal.tgz"
        tarball_bytes = _make_tarball_bytes(
            {
                "package/custom.yaml": "# ---\n# title: Custom Flow\n# ---\nname: custom\n",
            }
        )
        tarball_path.write_bytes(tarball_bytes)

        # Act
        meta = extract_tarball_metadata(
            tarball_path=tarball_path,
            source="owner/repo",
            version="1.0.0",
            manifest_data={
                "files": [
                    "not-a-dict",
                    {"source": "config.json", "target": "config.json"},
                    {"source": "custom.yaml", "target": ".github/workflows/custom.yaml"},
                ]
            },
        )

        # Assert
        assert meta["title"] == "Custom Flow"

    def test_extract_tarball_metadata_should_return_defaults_when_workflow_file_in_files_is_missing(
        self, tmp_path: Path
    ) -> None:
        # Arrange: tarball where files has a non-existent source
        tarball_path = tmp_path / "broken.tgz"
        tarball_path.write_bytes(_make_tarball_bytes({}))

        # Act
        meta = extract_tarball_metadata(
            tarball_path=tarball_path,
            source="owner/repo",
            version="1.0.0",
            manifest_data={"files": [{"source": "does-not-exist.yaml", "target": ".github/workflows/broken.yaml"}]},
        )

        # Assert
        assert meta["title"] is None

    def test_extract_tarball_metadata_should_return_defaults_when_tarball_is_corrupted(self, tmp_path: Path) -> None:
        # Arrange: invalid tarball file
        corrupt_path = tmp_path / "corrupt.tgz"
        corrupt_path.write_text("not a tarball")

        # Act
        meta = extract_tarball_metadata(
            tarball_path=corrupt_path,
            source="owner/repo",
            version="1.0.0",
            manifest_data={},
        )

        # Assert
        assert meta["title"] is None
        assert meta["source"] == "owner/repo"

    def test_extract_tarball_metadata_should_use_pre_extracted_files_when_provided(self, tmp_path: Path) -> None:
        # Arrange: tarball with workflow.yml but without primary workflow file in tarball
        workflow_yml = "name: my-flow\n"
        tarball_bytes = _make_tarball_bytes({"workflow.yml": workflow_yml})
        tarball_path = tmp_path / "pkg.tgz"
        tarball_path.write_bytes(tarball_bytes)

        files = [
            InstalledFile(
                source="flow.yml",
                content=b"# ---\n# title: Pre-Extracted Title\n# ---\nname: flow\n",
                target=".github/workflows/flow.yml",
            )
        ]

        # Act
        meta = extract_tarball_metadata(
            tarball_path=tarball_path,
            source="owner/repo",
            version="1.0.0",
            manifest_data={"files": [{"source": "flow.yml", "target": ".github/workflows/flow.yml"}]},
            files=files,
        )

        # Assert
        assert meta["title"] == "Pre-Extracted Title"


class TestFindPrimaryWorkflowSource:
    def test_find_primary_workflow_source_should_return_source_when_workflow_target_exists(self) -> None:
        # Arrange
        manifest_data = {
            "files": [
                {"source": "config.json", "target": "config.json"},
                {"source": "linter.yaml", "target": ".github/workflows/linter.yaml"},
            ]
        }

        # Act
        result = find_primary_workflow_source(manifest_data)

        # Assert
        assert result == "linter.yaml"

    def test_find_primary_workflow_source_should_return_none_when_no_workflow_target_exists(self) -> None:
        # Arrange
        manifest_data = {
            "files": [
                "invalid-item",
                {"source": "config.json", "target": "config.json"},
            ]
        }

        # Act
        result = find_primary_workflow_source(manifest_data)

        # Assert
        assert result is None

.DEFAULT_GOAL := help

.PHONY: help check-env install dev test lint format type-check clean build
.PHONY: lang lang-fix setup-precommit precommit super-linter super-linter-fix

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c

UV ?= uv
TEXTLINT_CONFIG ?= .github/linters/.textlintrc
TEXTLINT_IGNORE ?= .github/linters/.textlintignore

help:
	@echo "Available commands:"
	@echo ""
	@echo "python targets:"
	@echo "  check-env     - Ensure uv is available"
	@echo "  install       - Install package with dev deps (uv sync)"
	@echo "  dev           - Alias for install"
	@echo "  test          - Run pytest"
	@echo "  lint          - Run ruff linter"
	@echo "  format        - Run ruff formatter"
	@echo "  type-check    - Run mypy"
	@echo "  clean         - Remove build/test artifacts"
	@echo ""
	@echo "build targets:"
	@echo "  build            - Build sdist and wheel into dist/"
	@echo ""
	@echo "quality targets:"
	@echo "  lang             - Run textlint"
	@echo "  lang-fix         - Run textlint with --fix"
	@echo "  setup-precommit  - Install pre-commit hooks"
	@echo "  precommit        - Run pre-commit on all files"
	@echo "  super-linter     - Run super-linter via Docker"
	@echo "  super-linter-fix - Run super-linter with auto-fix"

check-env:
	@if command -v $(UV) >/dev/null 2>&1; then \
		echo "[check-env] uv found"; \
	else \
		echo "[check-env] ❌ uv not found; install it: https://docs.astral.sh/uv/getting-started/installation/"; \
		exit 1; \
	fi

install: check-env
	@echo "[install] Syncing dependencies (uv)..."
	@$(UV) sync

dev: install

test: install
	@echo "[test] Running pytest..."
	@$(UV) run pytest

lint: install
	@echo "[lint] Running ruff check..."
	@$(UV) run ruff check src/ tests/

format: install
	@echo "[format] Running ruff format..."
	@$(UV) run ruff format src/ tests/

type-check: install
	@echo "[type-check] Running mypy..."
	@$(UV) run mypy src/

clean:
	@echo "[clean] Removing build/test artifacts..."
	@rm -rf dist/ .pytest_cache/ .mypy_cache/ .ruff_cache/ .test-workspace/ .coverage coverage.xml pytest-coverage.txt junit.xml
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name '*.egg-info' -exec rm -rf {} + 2>/dev/null || true

build: clean check-env
	@echo "[build] Building sdist and wheel..."
	@$(UV) build

check-lang-env:
	@echo "[check-lang-env] Ensuring Node.js environment for textlint..."
	@which npx >/dev/null 2>&1 || (echo "[check-lang-env] ❌ npx not found; install Node.js" && exit 1)
	@npm install --no-save textlint textlint-rule-terminology textlint-filter-rule-comments >/dev/null 2>&1
	@echo "[check-lang-env] OK"

lang: check-lang-env
	@echo "[lang] Running textlint..."
	@npx textlint --config $(TEXTLINT_CONFIG) --ignore-path $(TEXTLINT_IGNORE) .

lang-fix: check-lang-env
	@echo "[lang-fix] Running textlint --fix..."
	@npx textlint --config $(TEXTLINT_CONFIG) --ignore-path $(TEXTLINT_IGNORE) . --fix

setup-precommit:
	@echo "[setup-precommit] Installing pre-commit hooks..."
	@pip install pre-commit
	@pre-commit install --install-hooks

precommit:
	@echo "[precommit] Running pre-commit..."
	@pre-commit run --all-files

super-linter:
	@echo "[super-linter] Running super-linter via Docker..."
	@GIT_DIR=$$(git rev-parse --path-format=absolute --git-common-dir) && \
	docker run \
		--platform linux/amd64 \
		-e RUN_LOCAL=true \
		-e DEFAULT_BRANCH=main \
		--env-file .github/super-linter.env \
		-v $(PWD):/tmp/lint \
		-v $$GIT_DIR:$$GIT_DIR \
		--rm \
		ghcr.io/super-linter/super-linter:slim-v8.6.0@sha256:a56c57c3fbe361bf07173c35c1a8bb3839fc64e363021fdb67798625ea3f3565

super-linter-fix:
	@echo "[super-linter-fix] Running super-linter with auto-fix via Docker..."
	@GIT_DIR=$$(git rev-parse --path-format=absolute --git-common-dir) && \
	docker run \
		--platform linux/amd64 \
		-e RUN_LOCAL=true \
		-e DEFAULT_BRANCH=main \
		--env-file .github/super-linter.env \
		--env-file .github/super-linter-fix.env \
		-v $(PWD):/tmp/lint \
		-v $$GIT_DIR:$$GIT_DIR \
		--rm \
		ghcr.io/super-linter/super-linter:slim-v8.6.0@sha256:a56c57c3fbe361bf07173c35c1a8bb3839fc64e363021fdb67798625ea3f3565

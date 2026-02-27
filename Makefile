.PHONY: help install-dev hooks-install fmt fmt-check lint test generate package-check version-check examples-check alloy-validate workflow-check act-ci preflight preflight-act verify

help:
	@echo "Targets:"
	@echo "  make preflight      - Install dev deps, format, verify format, run tests, validate generated.example"
	@echo "  make preflight-act  - Alias for make verify"
	@echo "  make verify         - Comprehensive local gate (lint, tests, package, workflows, act CI jobs)"
	@echo "  make hooks-install  - Configure git hooks to run local pre-push checks"
	@echo "  make fmt            - Apply ruff formatting"
	@echo "  make lint           - Run ruff lint checks"
	@echo "  make test           - Run pytest"
	@echo "  make generate       - Regenerate repo examples into generated.example/"
	@echo "  make package-check  - Build and smoke-test installed wheel"
	@echo "  make workflow-check - Lint GitHub Actions workflows with actionlint"
	@echo "  make act-ci         - Run CI jobs locally with act"
	@echo "  make alloy-validate - Parse-check generated Alloy configs with alloy fmt"

install-dev:
	uv pip install -e ".[dev]"

hooks-install:
	git config core.hooksPath .githooks

fmt:
	uv run ruff format .

fmt-check:
	uv run ruff format --check .

lint:
	uv run ruff check .

test:
	uv run pytest -q

generate:
	uv run alloygen --examples

package-check:
	uv build
	python scripts/package_check.py

version-check:
	uv run python scripts/check_version_bump.py --base-ref origin/main

examples-check:
	uv run alloygen --examples
	@git diff --quiet -- generated.example || (echo generated.example is out of date. Commit regenerated files. && git status --short generated.example && exit 1)

alloy-validate:
	uv run python scripts/check_alloy_configs.py generated.example

workflow-check:
	python scripts/require_tools.py actionlint
	actionlint -color

act-ci:
	python scripts/require_tools.py act
	act pull_request -W .github/workflows/ci.yml -j lint-test-examples
	act pull_request -W .github/workflows/ci.yml -j package

preflight: install-dev fmt fmt-check lint test version-check examples-check alloy-validate

verify: install-dev fmt-check lint test version-check examples-check alloy-validate package-check workflow-check act-ci

preflight-act: verify

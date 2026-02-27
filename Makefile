.PHONY: help install-dev hooks-install fmt fmt-check test version-check examples-check preflight preflight-act

help:
	@echo "Targets:"
	@echo "  make preflight      - Install dev deps, format, verify format, run tests, validate generated.example"
	@echo "  make preflight-act  - Run preflight, then run local GitHub Actions job with act"
	@echo "  make hooks-install  - Configure git hooks to run local pre-push checks"
	@echo "  make fmt            - Apply ruff formatting"
	@echo "  make test           - Run pytest"

install-dev:
	uv pip install -e ".[dev]"

hooks-install:
	git config core.hooksPath .githooks

fmt:
	uv run ruff format .

fmt-check:
	uv run ruff format --check .

test:
	uv run pytest -q

version-check:
	uv run python scripts/check_version_bump.py --base-ref origin/main

examples-check:
	uv run alloygen --examples
	@git diff --quiet -- generated.example || (echo generated.example is out of date. Commit regenerated files. && git status --short generated.example && exit 1)

preflight: install-dev fmt fmt-check test version-check examples-check

preflight-act: preflight
	act pull_request -j package

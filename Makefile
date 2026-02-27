.PHONY: help install-dev fmt fmt-check test examples-check preflight preflight-act

help:
	@echo "Targets:"
	@echo "  make preflight      - Install dev deps, format, verify format, run tests, validate generated.example"
	@echo "  make preflight-act  - Run preflight, then run local GitHub Actions job with act"
	@echo "  make fmt            - Apply ruff formatting"
	@echo "  make test           - Run pytest"

install-dev:
	uv pip install -e ".[dev]"

fmt:
	uv run ruff format .

fmt-check:
	uv run ruff format --check .

test:
	uv run pytest -q

examples-check:
	uv run alloygen --examples
	@git diff --quiet -- generated.example || (echo generated.example is out of date. Commit regenerated files. && git status --short generated.example && exit 1)

preflight: install-dev fmt fmt-check test examples-check

preflight-act: preflight
	act -j test

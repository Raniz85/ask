# Justfile for Ask project

# Run all checks (format, lint, typecheck, test)
check: format lint typecheck test

# Ensure dependencies are up to date
sync:
    uv sync

# Format code using ruff
format:
    dprint fmt

# Lint code using ruff
lint:
    uv run ruff check .

# Run type checking using mypy
typecheck:
    uv run mypy .

# Run tests with coverage
test:
    uv run pytest --cov=ask --cov-branch --cov-report=term-missing

# Run end-to-end tests in an Incus VM (set ASK_E2E_KEEP_VM=1 to keep the VM)
e2e:
    uv run pytest -m vm -v tests/vm

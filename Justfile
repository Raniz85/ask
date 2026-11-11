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

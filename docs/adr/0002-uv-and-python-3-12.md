# ADR 0002: uv for dependencies, Python 3.12 pinned

Status: Accepted

## Context
The backend needs reproducible installs and a fixed interpreter version across machines and CI.

## Decision
Dependencies are declared in `backend/pyproject.toml` and locked in `backend/uv.lock`, managed with uv. The interpreter is pinned to Python 3.12 in `backend/.python-version`. Dev-only tools (pytest, ruff, mypy, moto, type stubs) live in the dev dependency group.

## Consequences
- `uv sync` reproduces the environment; `uv run` is the command prefix for every tool.
- The lockfile is committed. Upgrading a dependency is a deliberate commit.
- Contributors need uv installed.

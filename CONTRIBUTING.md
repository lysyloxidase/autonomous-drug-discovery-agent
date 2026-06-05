# Contributing

Thanks for helping build Autonomous Drug Discovery Agent.

## Development Setup

```bash
uv sync --all-extras
uv run pre-commit install
```

## Quality Gates

Before opening a pull request, run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest
```

## Retrieval Tests

Unit tests must not call live APIs. Use mocked HTTP responses or VCR cassettes
that are safe to commit and do not contain credentials.

## Research Safety

Keep the research-only disclaimer visible when adding report or API surfaces.
Do not present outputs as clinical advice.


.PHONY: setup run test demo up lint typecheck

setup:
	uv sync --all-extras

run:
	uv run adda retrieve "$(DISEASE)" --max-results 50

demo:
	uv run adda retrieve "glioblastoma" --max-results 20

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run pyright

up:
	docker compose -f docker/docker-compose.yml up --build


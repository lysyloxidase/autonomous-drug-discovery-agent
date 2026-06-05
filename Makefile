.PHONY: setup run test demo up lint typecheck docs

setup:
	uv sync --all-extras
	uv run pre-commit install

run:
	uv run adda retrieve "$(DISEASE)" --max-results 50

demo:
	uv run python -m adda.cli run --disease "idiopathic pulmonary fibrosis"

test:
	uv run ruff check .
	uv run pyright
	uv run pytest --cov=adda

lint:
	uv run ruff check .
	uv run ruff format --check .

typecheck:
	uv run pyright

up:
	docker compose -f docker/docker-compose.yml up --build

docs:
	uv run mkdocs serve

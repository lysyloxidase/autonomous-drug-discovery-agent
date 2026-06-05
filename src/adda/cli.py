"""Command line interface."""

from __future__ import annotations

import asyncio

import typer

from adda.logging import configure_logging
from adda.retrieval.merge import assemble_corpus

app = typer.Typer(help="Autonomous Drug Discovery Agent")


@app.command()
def retrieve(
    disease: str = typer.Argument(..., help="Disease query, e.g. glioblastoma"),
    max_results: int = typer.Option(50, "--max-results", "-n", min=1),
    as_json: bool = typer.Option(False, "--json", help="Print full Corpus JSON"),
) -> None:
    """Retrieve a citation-grounded literature corpus for a disease."""

    configure_logging()
    corpus = asyncio.run(assemble_corpus(disease, max_results=max_results))
    if as_json:
        typer.echo(corpus.model_dump_json(indent=2))
        return

    typer.echo(f"Disease: {corpus.disease_query}")
    typer.echo(f"Publications: {len(corpus.publications)}")
    typer.echo(f"Cache hit: {corpus.cache_hit}")
    typer.echo("Per-source counts:")
    for source, count in sorted(corpus.per_source_counts.items()):
        typer.echo(f"  {source}: {count}")
    for publication in corpus.publications[:10]:
        identifiers = ", ".join(
            value
            for value in (publication.doi, publication.pmid, publication.pmcid)
            if value
        )
        suffix = f" ({identifiers})" if identifiers else ""
        typer.echo(f"- {publication.title}{suffix}")


if __name__ == "__main__":
    app()

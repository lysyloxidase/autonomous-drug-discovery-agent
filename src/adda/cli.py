"""Command line interface."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import typer

from adda.api.app import create_demo_tools
from adda.logging import configure_logging
from adda.orchestrator import CustomOrchestrator
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


@app.command("run")
def run_agent(
    disease: str = typer.Option(
        "idiopathic pulmonary fibrosis",
        "--disease",
        "-d",
        help="Disease query for the end-to-end demo pipeline.",
    ),
) -> None:
    """Run the deterministic demo agent pipeline and print a results table."""

    configure_logging()
    checkpoint_dir = Path(tempfile.gettempdir()) / "adda-cli-checkpoints"
    state = CustomOrchestrator(
        create_demo_tools(),
        checkpoint_dir,
        wait_multiplier=0,
    ).run(disease)

    publications = len(state.corpus.publications) if state.corpus else 0
    top_targets = ", ".join(
        f"{target.target_symbol} ({target.evidence_tier})"
        for target in state.target_scores[:5]
    )
    typer.echo(
        "| "
        + " | ".join(
            [
                "Disease",
                "Pubs",
                "Unique entities",
                "KG nodes",
                "KG relations",
                "Top-5 targets",
                "Citation accuracy",
            ]
        )
        + " |"
    )
    typer.echo("|---|---:|---:|---:|---:|---|---:|")
    typer.echo(
        "| "
        + " | ".join(
            [
                state.disease_query,
                str(publications),
                str(len(state.entities)),
                str(state.report_json.get("kg_nodes", len(state.entities) + 1)),
                str(state.report_json.get("kg_relations", 0)),
                top_targets,
                f"{state.citation_accuracy or 0:.4f}",
            ]
        )
        + " |"
    )
    typer.echo("")
    typer.echo(state.report_markdown or "")


if __name__ == "__main__":
    app()

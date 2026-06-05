# Real vs Mocked

Runtime retrieval uses live public APIs. Tests use mocks and local cache
backends so the suite is deterministic, fast, and credential-free.

Mocked tests verify normalization, rate limiting, retry behavior, cache hits,
OpenAlex abstract decoding, and deduplication semantics. VCR cassettes can be
added for periodic integration checks when API credentials and quotas are
available.

Extraction tests use BioC-shaped PubTator3 fixtures, fake scispaCy-like
pipelines, and mocked Ollama responses. This keeps the tests deterministic while
still exercising the same Pydantic schemas and parser paths used by live runs.

KG tests use mocked Neo4j and GDS clients, plus a Docker Compose config check
for APOC and Graph Data Science plugin declarations. Live Neo4j integration can
be added with testcontainers once CI has Docker service support.

Evidence tests use mocked Open Targets GraphQL responses. The production client
uses the official Open Targets Platform GraphQL endpoint and the same parser
paths covered by unit tests.

Ranking tests use local candidate fixtures to verify score components, weight
sensitivity, and known-target recovery. ChEMBL tests use fake Web Resource
Client resources so the unit suite does not depend on live EBI availability.
RDKit tests run real local descriptor, alert, fingerprint, and scaffold
computations.

Orchestrator tests use deterministic fake tools for retrieval, extraction, KG,
evidence, ranking, and triage. This exercises retries, checkpoint/resume,
streaming, LangGraph parity, and citation verification without calling live
services or LLMs.

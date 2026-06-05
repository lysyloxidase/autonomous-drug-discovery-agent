# Real vs Mocked

Runtime retrieval uses live public APIs. Tests use mocks and local cache
backends so the suite is deterministic, fast, and credential-free.

Mocked tests verify normalization, rate limiting, retry behavior, cache hits,
OpenAlex abstract decoding, and deduplication semantics. VCR cassettes can be
added for periodic integration checks when API credentials and quotas are
available.


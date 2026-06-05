from __future__ import annotations

from adda.retrieval.openalex import decode_inverted_index


def test_decode_inverted_index_reconstructs_abstract_exactly() -> None:
    inverted_index = {
        "Target": [0],
        "discovery": [1],
        "needs": [2],
        "grounded": [3],
        "citations.": [4],
    }

    assert (
        decode_inverted_index(inverted_index)
        == "Target discovery needs grounded citations."
    )

from __future__ import annotations

import httpx
import pytest
import respx

from adda.evidence.opentargets import (
    OpenTargetsClient,
    parse_association_row,
    parse_datatype_scores,
    parse_tractability,
)


def association_payload() -> dict[str, object]:
    return {
        "data": {
            "disease": {
                "id": "EFO_0000311",
                "associatedTargets": {
                    "count": 1,
                    "rows": [
                        {
                            "score": 0.91,
                            "target": {
                                "id": "ENSG00000141510",
                                "approvedSymbol": "TP53",
                                "tractability": [
                                    {
                                        "label": "Small molecule",
                                        "modality": "SM",
                                        "value": True,
                                    }
                                ],
                            },
                            "datatypeScores": [
                                {"id": "geneticAssociations", "score": 0.8},
                                {"id": "knownDrugs", "score": 0.2},
                            ],
                        }
                    ],
                },
            }
        }
    }


@pytest.mark.asyncio
@respx.mock
async def test_open_targets_associations_parse_scores_and_tractability() -> None:
    respx.post("https://ot.test/graphql").mock(
        return_value=httpx.Response(200, json=association_payload())
    )
    client = OpenTargetsClient(endpoint="https://ot.test/graphql")

    associations = await client.associations("EFO_0000311")
    await client.aclose()

    assert len(associations) == 1
    association = associations[0]
    assert association.target_id == "ENSG00000141510"
    assert association.target_symbol == "TP53"
    assert association.overall_score == 0.91
    assert association.datatype_scores == {
        "genetic_association": 0.8,
        "known_drug": 0.2,
    }
    assert association.known_drug is True
    assert association.tractability[0].label == "Small molecule"


@pytest.mark.asyncio
@respx.mock
async def test_open_targets_tractability_query_returns_buckets() -> None:
    respx.post("https://ot.test/graphql").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "target": {
                        "id": "ENSG00000141510",
                        "approvedSymbol": "TP53",
                        "tractability": [
                            {"label": "Antibody", "modality": "AB", "value": False}
                        ],
                    }
                }
            },
        )
    )
    client = OpenTargetsClient(endpoint="https://ot.test/graphql")

    tractability = await client.tractability("ENSG00000141510")
    await client.aclose()

    assert tractability["target_id"] == "ENSG00000141510"
    assert tractability["target_symbol"] == "TP53"
    assert tractability["tractability"][0]["modality"] == "AB"


@pytest.mark.asyncio
@respx.mock
async def test_open_targets_graphql_errors_raise() -> None:
    respx.post("https://ot.test/graphql").mock(
        return_value=httpx.Response(200, json={"errors": [{"message": "bad query"}]})
    )
    client = OpenTargetsClient(endpoint="https://ot.test/graphql")

    with pytest.raises(ValueError):
        await client.associations("EFO_0000311")

    await client.aclose()


def test_parse_helpers_accept_dict_and_skip_bad_rows() -> None:
    assert parse_datatype_scores({"literature": 1.5, "bad": "x"}) == {"literature": 1.0}
    assert (
        parse_tractability([{"label": "PROTAC", "value": "low"}, {"x": "y"}])[0].label
        == "PROTAC"
    )
    assert parse_association_row({"score": 0.5, "target": {}}, disease_id="EFO") is None

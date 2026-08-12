"""The documented surface has to be the real one.

Anything generated is worth a test, because a generator will happily describe an
endpoint that does something else.
"""

from __future__ import annotations

from typing import Any

from tests.api.conftest import Harness

EXPECTED = {
    ("get", "/api/bounties"): {"200", "422"},
    ("get", "/api/bounties/{bounty_id}"): {"200", "404", "422"},
    ("post", "/api/triage"): {"200", "404", "422"},
    ("post", "/api/triage/undo"): {"200", "422"},
    ("post", "/api/scan"): {"200", "409"},
    ("get", "/api/scan/events"): {"200"},
    ("get", "/api/meta"): {"200"},
    ("get", "/api/health"): {"200"},
}


async def spec(api: Harness) -> dict[str, Any]:
    response = await api.client.get("/openapi.json")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


async def test_every_route_documents_what_it_can_return(api: Harness) -> None:
    paths = (await spec(api))["paths"]
    found = {
        (verb, path): set(operation["responses"])
        for path, operations in paths.items()
        for verb, operation in operations.items()
    }

    assert found == EXPECTED


async def test_the_progress_stream_is_documented_as_one(api: Harness) -> None:
    """It is not JSON, and a client generated from this must not expect JSON."""
    operation = (await spec(api))["paths"]["/api/scan/events"]["get"]

    assert set(operation["responses"]["200"]["content"]) == {"text/event-stream"}


async def test_a_row_and_a_detail_are_distinct_in_the_schema(api: Harness) -> None:
    """The list does not carry bodies, and the schema has to say so."""
    schemas = (await spec(api))["components"]["schemas"]

    assert "body" not in schemas["BountyRow"]["properties"]
    assert "body" in schemas["BountyDetail"]["properties"]

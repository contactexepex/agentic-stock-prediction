"""The Companies page's command routes in the contract (B11; api/paths/companies.yaml previewCompanyCommand and
createCompanyCommand, web/lib/data/company-commands.ts): the bodies the page sends and the answers the routes give
(the key sets web/lib/data/tests/company-commands.test.ts checks on the real tool layer) validate against the bundled
schemas, and what the routes refuse (market or key in the arguments, another tool, unknown fields) does not."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from marketbrief.warehouse import openapi_spec, schema_check  # noqa: E402

RESOLVED = {"market": "us", "symbol": "MSFT", "name": "Microsoft Corporation", "exchange": "NASDAQ",
            "sector": "Technology", "yahoo": "MSFT", "nse_symbol": None, "cik": "0000789019", "amount": 2500,
            "amount_is_default": False, "currency": "USD"}
REACTIVATE = "reactivate_company"
PREVIEW_REQUEST = "CompanyCommandPreviewRequest"
RECEIPT = {"command_id": "cmd-1", "result": "pending", "refusal_code": None, "message": "Pending: Add Microsoft",
           "inbox_id": "key-0123456789abcdef", "record_ids": [], "budget_left": 49, "paper": True}


@pytest.fixture(scope="module")
def spec() -> dict:
    return openapi_spec.bundle()


def check(spec: dict, value, name: str) -> list[str]:
    return schema_check.errors(value, {"$ref": f"#/components/schemas/{name}"}, spec)


@pytest.mark.parametrize("value, name", [
    ({"tool": "add_company", "arguments": {"symbol": "MSFT", "amount": 2500}}, "CompanyCommandPreviewRequest"),
    ({"tool": "set_paper_amount", "arguments": {"ticker": "AAPL", "amount": None}}, "CompanyCommandPreviewRequest"),
    ({"tool": "delete_company", "arguments": {"ticker": "AAPL", "confirm": "AAPL"}, "confirmed_summary": "Delete AAPL"},
     "CompanyCommandSubmission"),
    ({"tool": "add_company", "summary": "Add Microsoft Corporation", "preview": RESOLVED,
      "arguments": {"symbol": "MSFT", "amount": 2500}, "paper": True}, "CompanyCommandPreview"),
    ({"tool": "deactivate_company", "summary": "Deactivate AAPL (US)", "preview": None,
      "arguments": {"ticker": "AAPL", "reason": "quiet"}, "paper": True}, "CompanyCommandPreview"),
    (RECEIPT, "CompanyCommandReceipt"),
    ({**RECEIPT, "result": "refused", "refusal_code": "validation_failed", "inbox_id": None, "budget_left": None},
     "CompanyCommandReceipt"),
])
def test_the_routes_bodies_and_answers_validate(spec, value, name):
    assert check(spec, value, name) == []


@pytest.mark.parametrize("value, name", [
    ({"tool": "add_paper_trade", "arguments": {"ticker": "AAPL"}}, PREVIEW_REQUEST),
    ({"tool": REACTIVATE, "arguments": {"ticker": "AAPL", "market": "india"}}, PREVIEW_REQUEST),
    ({"tool": REACTIVATE, "arguments": {"ticker": "AAPL", "idempotency_key": "k" * 16}}, PREVIEW_REQUEST),
    ({"tool": REACTIVATE, "arguments": {"ticker": "AAPL"}, "submitted_by": "x"}, PREVIEW_REQUEST),
    ({"tool": REACTIVATE, "arguments": {"ticker": "AAPL"}}, "CompanyCommandSubmission"),
    ({"tool": REACTIVATE, "arguments": {"ticker": "AAPL"}, "confirmed_summary": ""}, "CompanyCommandSubmission"),
])
def test_what_the_routes_refuse_does_not_validate(spec, value, name):
    assert check(spec, value, name) != []


def test_both_writes_take_the_key_and_are_post_only(spec):
    for path in ("/api/v1/markets/{market}/companies/preview", "/api/v1/markets/{market}/companies/commands"):
        item = spec["paths"][path]
        assert list(item) == ["post"]
        refs = [param.get("$ref") for param in item["post"]["parameters"]]
        assert "#/components/parameters/IdempotencyKey" in refs

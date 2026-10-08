# api/: the app API contract (OpenAPI 3.1)

Owner of the layout and the shared parts: session B4 (docs/ws/b4.md). Each page session owns its own files.

| File | Holds | Owner |
|---|---|---|
| `openapi.yaml` | info (version), servers, security, tags, the shared parameters, headers, responses and schemas (Market, Ticker, Horizon N+k, Problem, ReadModelMeta, PageHeader, HorizonChoice, StatusBlock, GoLive, StrategyEntry, ...), the platform paths (markets, status, internal revalidate) and the 1.0 paths | B4 |
| `paths/<page>.yaml` | a map of path -> path item: the page's operations | the page's session |
| `schemas/<page>.yaml` | a map of schema name -> schema: the page's payload and response schemas | the page's session |

Every `$ref` in every file is written against the bundled document (`#/components/schemas/Market`), because the
bundle merges all files into one: from `scripts/`, `python -m marketbrief.warehouse.openapi_spec > /tmp/openapi.json`
prints it (for code generators). A path or schema name defined in two files is an error. `tests/test_openapi.py`
checks the bundle; `tests/test_api_contract.py` checks every page's read models against it and against the page's
approved mockup (`design/mockups/<page>/data.json`).

Versioning: additions bump the minor version (1.1.0 is this wave's); a major version needs the owner. A page payload
uses catalogue fields only (`docs/DATA_CATALOGUE.md`); a missing field is a data request to W1.

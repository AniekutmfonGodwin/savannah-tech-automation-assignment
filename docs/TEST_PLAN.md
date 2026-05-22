# Test Plan

## Objective

Validate the assignment API before release with an automation framework that is maintainable, configurable, contract-aware, and easy to run in CI. The suite emphasises clean Pytest structure, reusable fixtures, environment-safe config, OpenAPI validation, tenant isolation, reporting, and one-command execution.

## Scope

In scope:

- Basic Authentication for preloaded users.
- Integration CRUD and pagination.
- Asset CRUD and integration scoping.
- Tenant segregation between `test1` and `test2`.
- Swagger/OpenAPI status and schema validation.
- Negative validation for malformed or incomplete input.
- Load check for at least 1000 requests per minute.

Out of scope:

- UI/Selenium coverage.
- Real cloud provider provisioning.
- Terraform-based infrastructure, because the assignment service is already distributed as a local Docker image.

## Architecture

The framework is layered so each concern is the responsibility of exactly one
module:

- **`Settings` + `env_loader`**: layered configuration (defaults → YAML profile
  → env vars → CLI `--env`). Secrets are referenced by env-var name in YAML so
  the same codebase runs on local Docker, GitHub Actions secrets, or Vault.
- **`ApiClient`**: the only HTTP entry point, with structured logging at DEBUG
  for trace-based debugging (a JD requirement).
- **`endpoints/` (service-objects)**: declarative wrappers around each
  resource. Tests read in domain terms ("create an aws integration"), not HTTP
  plumbing. Adding a new endpoint is a one-file change.
- **`OpenAPIContract`**: validates status codes and schemas against the live
  Swagger document, using the modern `referencing` library (no deprecated
  `RefResolver`).
- **`ResourceTracker`**: best-effort cleanup after each test, with per-resource
  failure logging.
- **`metrics`**: percentile helper (p100-safe; the previous `_percentile` had
  an off-by-one at p100).
- **Markers**: 12 categories so CI matrices can run `smoke` fast, `full` on
  schedule, `schemathesis` nightly. Destructive tests auto-skip on `read_only`
  environment profiles.
- **Docker Compose** for hermetic local + CI execution.
- **Binary/runtime inspection** of the supplied image focuses tests on
  implementation risks; see `IMAGE_ANALYSIS.md`.

Tests are organised by *risk area* (auth, contract, tenant, input validation,
HTTP semantics, pagination, concurrency, security, load) rather than by
endpoint, so failures communicate product risk clearly and the suite scales
linearly as the API grows.

## Coverage Matrix

| Area | Main checks | Module |
| --- | --- | --- |
| Auth, happy path | Missing, invalid, and valid Basic Auth credentials | `test_auth.py` |
| Auth, fuzz | 9 malformed-credential variants (empty user/password, bad base64, missing colon, case-sensitivity, Bearer instead of Basic, cross-credential mix, trailing space) plus 401-body leak check | `test_auth_fuzz.py` |
| Contract, surface | Swagger availability, declared routes, schema/status validation | `test_contract.py` |
| Contract, sweep | Every declared `(method, path)` exercised; doc-vs-runtime drift detected | `test_contract_full.py` |
| Contract, fuzz | Schemathesis property-based generation from Swagger (opt-in) | `test_contract_schemathesis.py` |
| Integrations | Create, list, get, update, delete, pagination, empty collection | `test_integrations.py` |
| Assets | Create, list by `integrationId`, get, update, delete, foreign-key check | `test_assets.py` |
| Tenant isolation, list/read/delete | Cross-tenant list/get/delete, cross-tenant asset create | `test_tenant_isolation.py` |
| Tenant isolation, deep | Cross-tenant PATCH/DELETE/PUT, `tenant_id` leak, user enumeration via 200/404 differential, `integrationId` filter ignored, pagination amplifier | `test_tenant_isolation_deep.py` |
| Input validation | Empty/oversize strings, unknown type enum, broken JSON, wrong Content-Type, PATCH on missing id, PUT path-vs-body id semantics, extra-field injection | `test_input_validation.py` |
| Negative legacy | Missing fields, malformed IDs, unknown IDs | `test_negative.py` |
| HTTP semantics | 405/415, trailing slash, response Content-Type, stack-trace leak detection | `test_http_semantics.py` |
| Pagination | `page=0`/`-1`, `limit=0`/`large`, non-numeric, default behaviour, off-by-one across pages | `test_pagination.py` |
| Concurrency | Concurrent POSTs with same name, double-DELETE idempotency | `test_concurrency.py` |
| Security smoke | Path traversal, XSS payload, oversized body, Unicode | `test_security_smoke.py` |
| Security pen-test (OWASP API Top 10) | Rate-limit / brute-force (API2), body-size / nesting (API4), undocumented routes (API5/API9), security headers / CORS / version disclosure (API8), auth-header smuggling, timing side-channel, CRLF | `test_security_pentest.py` |
| Load, 1000 RPM | Throughput, p95 latency, error rate ≤ 1% | `test_load.py` |
| Load, extended | Write-heavy 200 concurrent POSTs, per-endpoint p50/p95/p99 | `test_load_extended.py` |
| Load, Locust (bonus) | Mixed two-tenant scenario, HTML report | `locustfile.py` |

## Implementation Investigation

The supplied image contains a single Go binary rather than source files. Binary metadata and strings still expose important implementation clues:

- Gin route handlers are compiled from `/app/controller/integrations.go` and `/app/controller/assets.go`.
- Runtime routes differ from Swagger for integration update.
- Resource storage appears to use `map[string]*model.Integration` and `map[string]*model.Asset`.
- Request structs expose JSON tags, but no visible `binding:"required"` tags.

These findings drove the emphasis on contract drift, tenant filtering, direct object reference checks, and negative validation.

## Acceptance Criteria

- The full suite runs with `./scripts/run_tests.sh`.
- Reports are generated under `reports/`.
- Tests use fixtures and reusable client/factory helpers instead of duplicated setup.
- Product bugs fail with clear assertion messages.
- `BUGS.md` documents each found bug with expected behavior, actual behavior, reproduction, and impact.

## Notes

Failing tests are not framework failures. They reflect real product defects in the API under test, every failing assertion references a numbered entry in `BUGS.md` so the CI report doubles as the defect ledger.

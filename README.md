# Automation Engineer Home Assignment

A Pytest automation framework for the `infralightio/test-integration-api` service. It validates behaviour against the published Swagger 2.0 contract, hunts tenant-isolation defects, runs a 1000 RPM load gate, and includes a focused security audit organised around the OWASP API Security Top 10.

Everything in this repository was built and verified locally against the running container. Each finding in [`docs/BUGS.md`](docs/BUGS.md) has a reproducible curl command and a failing automated test. Each passing test pins a behaviour I want preserved.

## Quick start

```sh
./scripts/run_tests.sh
```

This builds the test container, starts the API container, runs the full suite, writes the reports under `reports/`, and tears down. The only prerequisite is Docker.

Expected outcome: the suite reports 27 passes and roughly 47 failures. The failures are real product defects in the API under test. Each one references a numbered entry in [`docs/BUGS.md`](docs/BUGS.md). Total wall time on a recent run was about 6 to 7 minutes.

## Where to read next

| If you have | Read this |
| --- | --- |
| 2 minutes | [`docs/EXECUTIVE_SUMMARY.md`](docs/EXECUTIVE_SUMMARY.md). Bug count by severity, OWASP audit summary, and a map from the JD requirements to where they live in this repo. |
| 10 minutes | [`docs/BUGS.md`](docs/BUGS.md). The full defect log: 17 distinct bugs with 30 plus concrete reproductions, severity, OWASP category, expected and actual behaviour, impact, and likely root cause. |
| 10 minutes | [`docs/TEST_PLAN.md`](docs/TEST_PLAN.md). Test strategy, framework architecture, coverage matrix per module, acceptance criteria. |
| 5 minutes | [`docs/IMAGE_ANALYSIS.md`](docs/IMAGE_ANALYSIS.md). What the Docker image and its binary tell us about the API's implementation; how those findings shaped the test surface. |

## Project layout

```
.
|-- README.md                  this file
|-- pyproject.toml             package metadata, pytest config, optional extras
|-- docker-compose.yml         API + test runner composition (pinned digest)
|-- Dockerfile.tests           test container image
|-- Makefile                   common operations (see "Make targets" below)
|-- locustfile.py              opt-in Locust mixed-tenant load scenario
|-- scripts/
|   |-- run_tests.sh           one-command full run
|   `-- inspect_image.sh       Docker image / binary inspector
|-- src/firefly_qa/            framework code (see "Architecture" below)
|-- tests/                     pytest modules organised by risk area
|-- config/environments/       layered YAML config (local / dev / staging / prod)
|-- docs/                      bug log, executive summary, test plan, image notes, evidence
|   `-- evidence/              curl evidence backing each entry in BUGS.md
|-- reports/                   generated artifacts (ignored by git except .gitkeep)
`-- .github/workflows/         GitHub Actions CI (matrix over smoke / full / load / fuzz / security)
```

## Architecture

The framework is layered so each concern lives in exactly one place.

- `src/firefly_qa/config.py` and `src/firefly_qa/env_loader.py`. Settings dataclass plus a layered YAML loader. Resolution order: built-in defaults, then YAML profile under `config/environments/<env>.yaml`, then `FIREFLY_*` environment variables, then `pytest --env=<name>` CLI flag. Secrets are referenced by env-var name in YAML and never stored in the file itself.
- `src/firefly_qa/client.py`. HTTP client with Basic Auth support, structured DEBUG logging on every request, and a `wait_for_service` helper that polls the spec endpoint at startup.
- `src/firefly_qa/endpoints/`. Service-object wrappers for `/integrations` and `/assets`. Tests read in domain terms ("create an aws integration") rather than HTTP plumbing.
- `src/firefly_qa/contract.py`. Swagger 2.0 contract validator. Uses the modern `referencing` library (the legacy `RefResolver` is deprecated). Exposes `assert_status_declared` and `assert_response_schema`.
- `src/firefly_qa/factories.py`. `ResourceTracker` for creating and best-effort cleaning up integrations and assets per test.
- `src/firefly_qa/metrics.py`. Percentile helper with safe p100 handling, used by the load tests.

Test files in `tests/` are organised by risk area, not by endpoint. Cross-tenant access is one parametrised matrix; the input-validation 500-on-bad-input cases are another; the security pen test is organised by OWASP category. Adding a new endpoint to one of these matrices is a one-line change.

## Test surface

| Marker | Modules | What it covers |
| ------ | ------- | -------------- |
| `auth` | `test_auth.py`, `test_auth_fuzz.py` | Basic auth happy path plus nine malformed-credential variants |
| `contract` | `test_contract.py`, `test_contract_full.py`, `test_contract_schemathesis.py` (opt-in) | Swagger parity, declared status codes, schema validation, full operation sweep, property-based fuzz |
| `tenant` | `test_tenant_isolation.py`, `test_tenant_isolation_deep.py` | Cross-tenant read/write/delete on integrations and assets, `tenant_id` leak, user enumeration, pagination amplifier |
| `input_validation`, `negative` | `test_input_validation.py`, `test_negative.py` | 500-on-bad-input, length caps, type enums, content-type, broken JSON, PATCH on missing id, PUT path-id semantics |
| `http_semantics` | `test_http_semantics.py` | 405 vs 404 on wrong methods, 415 on wrong Content-Type, trailing-slash redirect, response Content-Type, stack-trace leak detection |
| `pagination` | `test_pagination.py` | Default behaviour, off-by-one across pages, pagination metadata presence |
| `concurrency` | `test_concurrency.py` | Concurrent writes, double-DELETE idempotency |
| `security` | `test_security_smoke.py`, `test_security_pentest.py` | Path traversal, XSS, Unicode (smoke). OWASP API Top 10: rate limit and brute-force (API2), body size and JSON nesting (API4), undocumented routes (API5/API9), security headers and CORS and version disclosure (API8), auth-header smuggling, timing side-channel, CRLF |
| `load` | `test_load.py`, `test_load_extended.py` | 1000 RPM gate with p95 latency, write-heavy variant with per-endpoint percentiles |

## Configuration

The framework is configured through layered YAML profiles. Each profile selects a base URL, request timeout, load knobs, and a reference (by env-var name) to the credentials for each pre-populated tenant.

```sh
# Default profile is "local". Pick a different one with either of:
pytest --env=staging
FIREFLY_ENV=dev pytest -m smoke
```

Available profiles: `local`, `dev`, `staging`, `prod`. The `prod` profile sets `read_only: true`, which auto-skips any test tagged `@pytest.mark.destructive` or `@pytest.mark.load`.

Secrets stay in environment variables. The YAML only stores the variable name to look up. See [`.env.example`](.env.example) for every supported override.

## Make targets

| Target | What it runs |
| --- | --- |
| `make test` | Full Docker Compose run (same as `./scripts/run_tests.sh`) |
| `make smoke` | Smoke-tagged tests only, fast PR gate |
| `make contract` | Contract-tagged tests only |
| `make security` | OWASP-organised pen test suite |
| `make fuzz` | Schemathesis property-based contract fuzz (opt-in) |
| `make load` | Pytest load profiles (1000 RPM plus write-heavy) |
| `make load-locust` | Locust mixed-tenant scenario with HTML report |
| `make inspect` | Inspect the API image and binary, write to `reports/image_inspection.txt` |
| `make lint` | Ruff plus mypy on the framework source |
| `make api-up` | Start the API container detached, wait for readiness |
| `make api-down` | Stop and remove the API container |
| `make api-restart` | Restart the API to clear its in-memory store |
| `make api-logs` | Tail the API container logs |
| `make clean` | Remove `reports/` and pytest caches |

## Generated artifacts

`./scripts/run_tests.sh` writes everything under `reports/`.

| File | What it contains |
| --- | --- |
| `reports/report.html` | Full HTML test report from pytest-html |
| `reports/security.html` | HTML report for `make security` |
| `reports/junit.xml` | CI-consumable JUnit XML |
| `reports/load_summary.json` | 1000 RPM load metrics (throughput, p95, error rate) |
| `reports/load_summary_writes.json` | Write-heavy load metrics (p50, p95, p99) |
| `reports/image_inspection.txt` | Output of `make inspect` |

The captured curl evidence that backs each bug entry lives under `docs/evidence/` and is committed with the repository.

## CI

`.github/workflows/tests.yml` runs the suite on every push and pull request, and nightly. The matrix has five axes: `smoke` for a fast PR gate, `full` for the everything-but-load run, `load` for the 1000 RPM gate, `security` for the pen test suite, and `fuzz` for the opt-in Schemathesis property fuzz. Each axis writes its own artifact and emits a markdown summary table back to the GitHub job summary, so reviewers see pass and fail counts without opening artifacts.

QEMU is set up before Docker Compose runs because the image is built for `linux/arm64` while GitHub runners default to `linux/amd64`.

## Why tests fail in the default run

The default run reports failures because the API under test contains 17 documented defects. Each failing assertion carries a `docs/BUGS.md#N` reference so the CI report doubles as the defect ledger. The functional bugs are documented in [`docs/BUGS.md`](docs/BUGS.md) entries 1 through 12; the security findings are entries 13 through 17.

If a future run goes fully green, the underlying bugs have been fixed. The next step would be to convert the now-pinned correct behaviour into regression assertions (most are already there as positive checks, so usually nothing further is needed).

## How this maps to the assignment

The job description ranks engineering signals as: clean code, then Pytest depth, CI ownership, configuration and secret management, IaC, cloud awareness, OpenAPI and contract testing. Every architectural decision in this repo maps to one of those lines. The full mapping table is in [`docs/EXECUTIVE_SUMMARY.md`](docs/EXECUTIVE_SUMMARY.md) under "Assignment requirements mapped to where they live in this repo".

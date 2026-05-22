# Executive Summary

A short read for the reviewer. Deeper detail in [BUGS.md](BUGS.md), strategy in [TEST_PLAN.md](TEST_PLAN.md), framework rationale in [../README.md](../README.md).

## What this is

A Pytest automation framework for the supplied REST API. One command (`./scripts/run_tests.sh`) builds the test container, starts the API container, executes the suite, and produces HTML, JUnit XML, and JSON reports. Configuration switches per environment via YAML profiles under `config/environments/`. The framework is designed to extend to new endpoints, new tenants, and new cloud providers without code changes.

## Bugs found

Several defects share the same root cause manifesting on multiple endpoints, so I grouped them under one bug with several reproductions. The 17 entries below capture everything; each has multiple test cases pinning the boundary.

| # | Severity | Area | Title |
| - | -------- | ---- | ----- |
| 1 | Critical | tenant | Tenant ownership is not enforced on resource-scoped endpoints. Nine reproductions: list leak, GET/DELETE/PUT on integrations, GET/PATCH/DELETE on assets, asset created under foreign integration, `?limit=999999` exfiltration. |
| 2 | Critical | tenant | Resource existence and `tenant_id` leaked via differential responses. |
| 3 | High | tenant | `GET /assets?integrationId=...` filter silently ignored. |
| 4 | High | contract | Documentation vs runtime drift: POST returns 201 but spec says 200; `PUT /integrations` declared but unrouted; `PUT /integrations/{id}` honours body id instead of path id. |
| 5 | High | integrity | `PUT /integrations/{id}` does not persist updates. |
| 6 | High | integrity | Assets can be created for nonexistent integrations. |
| 7 | High | validation | Server returns 500 on malformed user input (empty body, empty name, missing PATCH id, invalid or non-numeric page or limit, deeply nested JSON). |
| 8 | Medium | shape | List responses do not follow standard collection conventions (empty lists return `null`; populated lists carry no pagination metadata, so clients cannot tell when paging is done). |
| 9 | Medium | validation | No length cap on `name`. |
| 10 | Medium | validation | `type` field is not constrained to a known enum. |
| 11 | Medium | semantics | Wrong `Content-Type` accepted as JSON. |
| 12 | Medium | semantics | Unsupported HTTP methods return 404 instead of 405. |
| 13 | Critical | security (API2) | No rate limiting or brute-force protection. 100 wrong passwords succeed in 3 seconds; 1000 burst requests accepted. |
| 14 | Medium | security (API8) | Standard security response headers are all missing (`X-Content-Type-Options`, `X-Frame-Options`, HSTS, CSP, `Referrer-Policy`, `Cache-Control`). |
| 15 | Medium | security (API4) | No request body size limit (5 MB body accepted). |
| 16 | Low | security | Duplicate `Authorization` headers are not rejected. First-wins semantics create a smuggling risk behind reverse proxies. |
| 17 | Low | security | CRLF is stored verbatim in resource fields. Downstream log and webhook consumers become vulnerable to injection. |

Total: 17 distinct defects (4 Critical, 4 High, 7 Medium, 2 Low) with 30 plus concrete reproductions across the suite.

## Security audit (OWASP API Security Top 10, 2023)

| OWASP category | Coverage | Findings |
| --- | --- | --- |
| API1, Broken Object Level Authorization | `test_tenant_isolation*.py` | Bug #1 (nine reproductions) |
| API2, Broken Authentication | `test_security_pentest.py`, `test_auth_fuzz.py` | Bug #13 (no rate limit); auth fuzz passing |
| API3, Broken Object Property Level Authorization | `test_input_validation.py` | Bug #1 (mass-assignment sub-case) |
| API4, Unrestricted Resource Consumption | `test_security_pentest.py`, `test_input_validation.py` | Bug #15 (no body cap); bug #7 sub-case (deep nesting) |
| API5, Broken Function Level Authorization | `test_security_pentest.py` | Positive finding: no debug routes reachable |
| API7, Server Side Request Forgery | not applicable (no outbound from this API) | |
| API8, Security Misconfiguration | `test_security_pentest.py` | Bug #14 (missing headers); positive: no version leak, no CORS reflection |
| API9, Improper Inventory Management | `test_contract_full.py`, `test_security_pentest.py` | Bug #4 (doc vs runtime drift) |

## Why these bugs matter

Tenant isolation is the highest-stakes property of any multi-tenant API. Every cross-tenant leak above (bugs 1, 2, 3, plus the asset variants grouped under bug 1) would be a P0 if found in production. Bugs 4, 5, and 6 are documentation versus runtime drift, which makes real regressions hard to distinguish from deliberate API changes. Bugs 7, 9, 10, 11, 13, 14, and 15 are the kind of input handling and security hygiene gaps that a SOC 2 or ISO 27001 audit would flag immediately. The framework catches all 17 today and pins the boundary for future regressions.

## Assignment requirements mapped to where they live in this repo

| Requirement | Where to find it |
| --- | --- |
| 1. Clean code and framework health | `src/firefly_qa/`: typed dataclasses, frozen settings, service-object endpoints (`endpoints/integrations.py`, `endpoints/assets.py`), `metrics.py` percentile helper, structured logging in `client.py`. Markers and parametrisation in every test module. |
| 2. Pytest depth | Markers in `pyproject.toml` (12 distinct categories). Fixtures in `tests/conftest.py` scoped to session or function appropriately. `pytest_collection_modifyitems` to auto-skip destructive tests on read-only environments. `--env=<profile>` CLI flag. Optional `pytest-xdist` for parallel runs. |
| 3. CI and GitHub Actions | `.github/workflows/tests.yml`: matrix over `[smoke, full, load, fuzz, security]` axes, artifact upload, GitHub Summary table, dependency caching. |
| 4. Configuration and secret management | `config/environments/*.yaml` for environment profiles; secrets are referenced by env-var name (`password_env:`) and never stored in YAML. `env_loader.py` implements layered resolution: defaults, then YAML profile, then env vars, then CLI `--env`. `.env.example` documents every supported variable. |
| 5. Infrastructure as Code | `docker-compose.yml` (pinned digest), `Dockerfile.tests`, and `scripts/run_tests.sh` provision the test environment reproducibly. |
| 6. Cloud awareness | `config/environments/{dev,staging,prod}.yaml` are modelled on a real multi-region SaaS layout; `read_only: true` on prod enforces non-destructive runs. |
| 7. OpenAPI and contract testing | `src/firefly_qa/contract.py` validates declared status codes and response schemas (modern `referencing` library, no deprecated `RefResolver`). `tests/test_contract_full.py` sweeps every declared operation. `tests/test_contract_schemathesis.py` adds opt-in property-based fuzz via Schemathesis. |
| 8. Python proficiency | Type-hinted everywhere, frozen dataclasses, `Iterator` fixture pattern, no global state, no string-template duplication (page-object endpoints). Ruff and mypy configured in `pyproject.toml`. |
| 9. Docker and dev workflows | One-command `./scripts/run_tests.sh`. QEMU step in CI for the `linux/arm64` image on `linux/amd64` runners. `Makefile` for common operations. |
| Bonus: load testing | `tests/test_load.py` (1000 RPM gate, p95 latency), `tests/test_load_extended.py` (write-heavy plus percentiles), and `locustfile.py` (mixed two-tenant scenario with HTML report). |

## How to run

```sh
./scripts/run_tests.sh                      # default: full suite plus reports
pytest -m smoke                             # fast PR gate
pytest -m "not load and not schemathesis"   # everything but the heavy bits
FIREFLY_ENV=staging pytest -m smoke         # against the staging profile
make security                               # pen-test suite in isolation
make fuzz                                   # opt-in Schemathesis property fuzz
make load-locust                            # opt-in Locust scenario
```

## Generated artifacts

- `reports/report.html`: HTML test report
- `reports/security.html`: HTML security report (via `make security`)
- `reports/junit.xml`: CI-consumable test results
- `reports/load_summary.json`, `reports/load_summary_writes.json`: load metrics
- `evidence/probe_log.txt`: curl evidence backing each functional entry in BUGS.md
- `evidence/pentest_log.txt`: curl evidence backing each security entry in BUGS.md
- `evidence/image_inspection.txt`: Docker image and binary analysis output

## Note on failing tests

Failures in the default run come from the API under test, not the framework. Every failing assertion references a numbered `BUGS.md` entry, so the CI report doubles as the defect ledger.

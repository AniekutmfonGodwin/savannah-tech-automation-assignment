# Bug Report

This is the defect log I compiled while validating `infralightio/test-integration-api` before release. Each issue is reproducible against the running container, has a failing automated test in this repository, and was verified manually with `curl` to capture exact request and response evidence. The evidence files are in [`evidence/probe_log.txt`](evidence/probe_log.txt) (functional bugs) and [`evidence/pentest_log.txt`](evidence/pentest_log.txt) (security findings).

Where the same underlying defect manifests on multiple endpoints I have grouped the cases under one bug, since fixing the root cause fixes every sub-case at once. The "Reproductions" lists give the concrete examples a developer can use to repro and to confirm a fix.

For each bug I also tried to identify a likely root cause from the Go binary inside the Docker image. The image ships without source, but the binary's symbols, route table, embedded source paths, and model JSON tags are enough to make the hypotheses below well-grounded rather than speculative. The full inspection notes are in [`IMAGE_ANALYSIS.md`](IMAGE_ANALYSIS.md).

## Severity summary

| Severity | Count | Theme |
| --- | --- | --- |
| Critical | 4 | Multi-tenant isolation, no brute-force protection |
| High | 4 | Contract drift, referential integrity, server crashes on user input |
| Medium | 7 | Response shape, input validation, HTTP semantics, missing security headers, no body size limit |
| Low | 2 | Defense-in-depth gaps (duplicate auth header, CRLF in stored values) |

---

## 1. Tenant ownership is not enforced on resource-scoped endpoints (Critical)

The API stores `tenant_id` on every resource but the handlers never verify the caller's tenant against the resource's owner. That single missing check shows up on every endpoint that accepts a resource id (or a foreign id in the body / query string).

- **Tests:**
  - `tests/test_tenant_isolation.py` (list, GET, DELETE, asset create)
  - `tests/test_tenant_isolation_deep.py` (PATCH /assets, DELETE /assets/{id}, PUT /integrations/{id}, pagination amplifier)
- **Expected:** Every read or write that targets a resource owned by another tenant returns `403` or `404`. List endpoints filter by `tenant_id` before pagination.
- **Actual:** Reads succeed with `200` and the resource body. Writes/deletes succeed and persist. The collection list returns every tenant's rows.
- **Impact:** P0 for any multi-tenant service. Direct object reference for reads, destructive writes across tenant boundaries, and trivial mass-extraction by a single attacker request.
- **Likely root cause:** A single `currentTenant(ctx)` guard missing in `controller/integrations.go` and `controller/assets.go` before each handler touches the in-memory map.
- **Reproductions:**
  - **1a.** list leak: `GET /api/v1/integrations` as `test1` returns rows owned by `test2`.
  - **1b.** cross-tenant GET: `GET /api/v1/integrations/<test1's id>` as `test2` returns `200` and the body.
  - **1c.** cross-tenant DELETE on integrations: `DELETE /api/v1/integrations/<test1's id>` as `test2` destroys the resource.
  - **1d.** cross-tenant PUT on integrations: `PUT /api/v1/integrations/<test1's id>` as `test2` returns `200` (combined with bug #3 the write is silently no-op today, but the auth-layer rejection is missing, a future fix to #3 would silently turn this into a destructive write).
  - **1e.** cross-tenant GET on assets: `GET /api/v1/assets/<test1's id>` as `test2` returns `200` and the body.
  - **1f.** cross-tenant PATCH on assets: `PATCH /api/v1/assets` with `{ "id": "<test1's id>", … }` as `test2` rewrites `test1`'s asset.
  - **1g.** cross-tenant DELETE on assets: `DELETE /api/v1/assets/<test1's id>` as `test2` returns `204` and destroys the asset.
  - **1h.** asset created under foreign integration: `POST /api/v1/assets` as `test2` with `integration_id` set to a `test1` integration returns `201`; the asset is stored under `test2` but references the foreign integration.
  - **1i.** pagination amplifier: `GET /api/v1/integrations?limit=999999` returns every integration from every tenant in a single response. A trivial bulk-exfiltration vector.

## 2. Resource existence and `tenant_id` are leaked via differential responses (Critical)

Two related side-channels in the cross-tenant read path:

- **Tests:** `tests/test_tenant_isolation_deep.py::test_resource_existence_is_not_distinguishable_via_status_code`, `…::test_tenant_id_is_not_leaked_to_other_tenants`.
- **Expected:** A missing id and another tenant's id should be indistinguishable. Responses must not include the owning tenant's identifier.
- **Actual:** Random ids return `404 {"error":"integration not found"}`; another tenant's id returns `200` and the body, which itself carries `"tenant_id":"test2"`.
- **Impact:** Allows an attacker to enumerate which ids belong to which tenants and to map customer tenant identifiers.
- **Reproductions:**
  - `GET /api/v1/integrations/00000000-0000-0000-0000-000000000000` → `404`
  - `GET /api/v1/integrations/<test2's id>` as `test1` → `200` with `"tenant_id":"test2"` in the body

## 3. `GET /assets?integrationId=…` query filter is silently ignored (High)

- **Test:** `tests/test_tenant_isolation_deep.py::test_asset_list_with_foreign_integration_id_must_not_leak`
- **Expected:** The `integrationId` query parameter restricts the result set to assets belonging to that integration.
- **Actual:** The filter is dropped entirely, the response is the caller's own assets regardless of the value passed.
- **Impact:** Documented filtering behaviour does not work. Clients that depend on it (UI grids, downstream pipelines) will silently return the wrong rows.

---

## 4. Documentation does not match runtime behaviour (High)

The published Swagger contract and the registered Gin routes disagree on three fronts. Each disagreement is a bug because client SDKs generated from the spec will be broken in production.

- **Tests:** `tests/test_contract.py`, `tests/test_contract_full.py`, `tests/test_input_validation.py::test_put_integration_path_id_must_take_precedence`.
- **Expected:** Runtime behaviour matches `/swagger/doc.json`.
- **Actual / Reproductions:**
  - **4a.** status code drift: `POST /api/v1/integrations` returns `201 Created`, but Swagger declares only `200`.
  - **4b.** undocumented vs documented route: Swagger declares `PUT /api/v1/integrations`, but the route is unregistered (`404`). The route that DOES exist, `PUT /api/v1/integrations/{id}`, is undocumented.
  - **4c.** path-id vs body-id ambiguity: `PUT /api/v1/integrations/<A>` with body `{ "id": "<B>", … }` returns the resource for `<B>`. The path id is silently discarded. RFC 7231 / general REST convention: the path id is authoritative.
- **Impact:** Generated clients and Code Connect-style mappings will call broken routes or misroute writes; integration tests that drive the API from the spec will appear to pass while production traffic fails.

## 5. `PUT /integrations/{id}` does not persist updates (High)

- **Test:** `tests/test_integrations.py::test_integration_lifecycle_create_get_update_delete`
- **Expected:** `PUT` mutates the resource and a subsequent `GET` reflects the change.
- **Actual:** The response body shows the updated values but the underlying record is unchanged (verified by re-reading).
- **Impact:** Successful-looking writes that are not actually persisted. Clients believe their updates succeeded; the data tells a different story.

## 6. Assets can be created for nonexistent integrations (High)

- **Test:** `tests/test_assets.py::test_creating_asset_requires_existing_integration`
- **Expected:** `POST /api/v1/assets` with an unknown `integration_id` returns `404` or `400`.
- **Actual:** Returns `201` and stores the asset with the dangling id.
- **Impact:** Referential integrity is broken. Downstream pipelines that join assets to integrations will surface orphaned rows.

## 7. Service returns 500 on malformed user input (High)

User-controllable input on validated endpoints should always produce a 4xx with a typed error body. Several inputs currently crash the handler and return `500 {"error":"internal server error"}`.

- **Tests:** `tests/test_negative.py`, `tests/test_input_validation.py`, `tests/test_pagination.py`.
- **Impact:** Each 500 is a small DoS vector and produces noisy alerts in production observability. It also reveals that input is reaching code paths that do not expect it, usually a sign of unvalidated DTOs.
- **Reproductions:**
  - **7a.** empty body: `POST /api/v1/integrations` with `{}` → `500`. Required fields are not enforced before being read.
  - **7b.** empty `name`: `POST /api/v1/integrations` with `{"name":"","type":"aws"}` → `500`.
  - **7c.** missing `type` (variant of 7a): `POST /api/v1/integrations` with `{"name":"x"}` is accepted with `201` and an empty `type` stored, same root-cause class (no required-field validation).
  - **7d.** PATCH on missing id: `PATCH /api/v1/assets` with `{ "id": "<missing>", … }` → `500` instead of `404`.
  - **7e.** invalid `page`: `GET /api/v1/integrations?page=0` and `?page=-1` → `500`.
  - **7f.** non-numeric `page` / `limit`: `?page=abc` and `?limit=abc` → `500`.
  - **7g.** deeply nested JSON body: `POST /api/v1/integrations` with a body nested 1 000 levels deep → `500`. Recursive parser with no depth cap is a stack-overflow / DoS vector. (Also referenced from bug #15, combined with no body size limit, this is a one-curl DoS.)

---

## 8. List responses do not follow standard collection conventions (Medium)

The list endpoints are missing two related pieces of REST collection contract, empty-collection serialisation and pagination metadata. They are filed together because the fix lives in the same place (the list-response serialiser).

- **Tests:**
  - `tests/test_integrations.py::test_list_integrations_returns_array_when_empty`
  - `tests/test_pagination.py::test_list_response_exposes_pagination_metadata`
- **Expected:**
  - Empty collections serialise as `[]`.
  - The response exposes enough information for a client to know whether another page exists, either an envelope with `total` / `total_pages` / `has_next`, or `X-Total-Count` / `Link` response headers.
- **Actual:**
  - **8a.** empty-list shape: `GET /api/v1/integrations` returns JSON `null` before any rows exist.
  - **8b.** no pagination metadata: populated responses are a bare array (`[...]`) with no envelope, no `total` / `has_next` / `next_page`, and no `X-Total-Count` / `Link` headers. The only response headers are `Content-Type`, `Content-Length`, and `Date`.
- **Impact:**
  - Forces every client to special-case `null` vs array (8a). Typed SDKs generated from the spec break at the first call.
  - Clients cannot tell when paging is done short of fetching pages until they get a short / empty response, wasted round trips, ugly UI ("..." next-page buttons that never resolve). Generated SDKs cannot expose a clean iterator.
- **Likely root cause:** The list handler returns a `nil` Go slice and writes no envelope; the in-memory store also does not expose a count.  Fix is initialise the slice with `make([]…, 0)` and wrap the response in `{ "data": [...], "page": …, "per_page": …, "total": … }` (or set `X-Total-Count`).
- **Reproduction:**
  - 8a: empty store, `curl -u test1:test123 http://localhost:8080/api/v1/integrations` → body is `null`.
  - 8b: populated store, same request returns `[{...},{...}]` with no metadata; `curl -I` confirms no pagination-related response headers.

## 9. No length cap on `name` (Medium)

- **Test:** `tests/test_input_validation.py::test_oversize_name_must_be_capped`
- **Expected:** Reject names beyond a documented maximum (typically 256 chars).
- **Actual:** Accepts 5 000+ character names with `201`.
- **Impact:** Resource-exhaustion vector, the in-memory store can be inflated arbitrarily. Logs and downstream consumers will balloon too.

## 10. `type` field is not constrained to a known enum (Medium)

- **Test:** `tests/test_input_validation.py::test_unknown_integration_type_must_be_rejected`
- **Expected:** `type` is restricted to a known set (e.g. `aws`, `gcp`, `azure`, `k8s`).
- **Actual:** Accepts any string, including arbitrary garbage like `"fictional-cloud"`.
- **Impact:** Invalid domain data leaks into the system. Combined with bug #7c (empty `type` accepted), the integrity of every downstream consumer that branches on `type` is at risk.

## 11. Wrong `Content-Type` is accepted as JSON (Medium)

- **Test:** `tests/test_input_validation.py::test_wrong_content_type_must_be_rejected`
- **Expected:** `415 Unsupported Media Type` when the body is JSON-shaped but the header says `text/plain`.
- **Actual:** The server happily parses the body and returns `201`.
- **Impact:** Quiet protocol violation, clients with broken `Content-Type` handling will appear to work in dev and fail behind a stricter API gateway in prod.

## 12. Unsupported HTTP methods return 404 instead of 405 (Medium)

- **Tests:** `tests/test_http_semantics.py::test_post_on_collection_member_must_be_405_not_404`, `…::test_patch_on_integration_member_must_be_405_not_404`.
- **Expected:** RFC 7231: `405 Method Not Allowed` (with an `Allow` header) when the path exists but the method does not.
- **Actual:** Falls through to Gin's catch-all `404 page not found`.
- **Reproductions:** `POST /api/v1/integrations/{id}`, `PATCH /api/v1/integrations/{id}`.
- **Impact:** SDKs and proxies that distinguish 404 vs 405 (for retry policy, route discovery, OPTIONS computation) take the wrong path.

---

---

# Penetration test findings

The bugs below came out of a security-focused pass against the running API, mapped to the OWASP API Security Top 10 (2023). Live curl evidence is in [`evidence/pentest_log.txt`](evidence/pentest_log.txt); tests live in `tests/test_security_pentest.py`. Several of the categories I probed are already secure on this service. I encoded those as passing tests in the same module so a future regression is caught.

## 13. No rate limiting on authentication or general traffic (Critical, OWASP API2:2023)

- **Test:** `tests/test_security_pentest.py::test_brute_force_is_rate_limited`, `…::test_authenticated_burst_is_rate_limited`
- **Expected:** Repeated failed auth attempts trigger throttling (HTTP 429) or progressive delay; a sustained burst of authenticated requests sees back-pressure.
- **Actual:** 100 wrong-password attempts complete in **3.16 s with 100 × 401**, no 429, no progressive delay, no lockout. A 1 000-request authenticated burst returns **1 000 × 200**, again with no 429s.
- **Impact:** Trivial password brute-force and credential-stuffing attacks. With Basic Auth on a multi-tenant SaaS, this is the easiest path to account takeover. Also enables resource-exhaustion DoS, any unauthenticated client can saturate the service.
- **Reproduction:**
  ```sh
  for i in $(seq 1 100); do \
    curl -s -o /dev/null -w "%{http_code}\n" -u test1:wrong-$i \
      http://localhost:8080/api/v1/integrations ; \
  done | sort | uniq -c
  #   100 401
  ```
- **Likely root cause:** The Gin router has no rate-limit middleware mounted. Fix: add `gin-contrib/timeout` + an in-memory or Redis token-bucket middleware applied globally and a stricter bucket on the auth path.

## 14. Standard security response headers are missing (Medium, OWASP API8:2023)

- **Tests:** `tests/test_security_pentest.py::test_response_includes_security_header[…]` (6 parametrised cases).
- **Expected:** API responses include the baseline secure headers recommended by the OWASP Secure Headers Project.
- **Actual:** The only response headers are `Content-Type`, `Date`, and `Transfer-Encoding`. None of the following are present:
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: DENY`
  - `Strict-Transport-Security` (HSTS)
  - `Content-Security-Policy`
  - `Referrer-Policy`
  - `Cache-Control` (tenant data should be `no-store`)
- **Impact:** MIME-sniffing attacks, clickjacking, TLS downgrade on intermediaries, sensitive data being cached by intermediate proxies. A SOC 2 / ISO 27001 audit would flag this immediately.
- **Likely root cause:** Gin app does not mount a "secure headers" middleware. Fix: `gin-contrib/secure` or equivalent, applied at the engine level.

## 15. No request body size limit (Medium, OWASP API4:2023)

- **Test:** `tests/test_security_pentest.py::test_request_body_has_a_size_limit`
- **Expected:** Bodies above a documented limit (typically 1 MB for JSON APIs) are rejected with `413 Payload Too Large`.
- **Actual:** A 5 MB JSON body is accepted with `201 Created` in ~430 ms.
- **Impact:** Resource-exhaustion vector. Combined with the in-memory store (`IMAGE_ANALYSIS.md`) and the absence of rate limiting (bug #13), a single client can balloon memory until OOM. Combined with bug #7g (deep-nesting crash), one large + nested payload is a one-curl DoS.
- **Likely root cause:** No `r.MaxMultipartMemory` / `http.MaxBytesReader` wrapper on the request body. Fix: cap to 256 KB or 1 MB at the Gin engine.

## 16. Duplicate `Authorization` headers are not rejected (Low, defense in depth)

- **Test:** `tests/test_security_pentest.py::test_multiple_authorization_headers_are_rejected`
- **Expected:** A request carrying two `Authorization` headers is rejected with `400 Bad Request` (ambiguous auth).
- **Actual:** The server first-wins, `Authorization: <valid>` then `Authorization: <wrong>` returns `200`. Order matters: `<wrong>` then `<valid>` returns `401`.
- **Impact:** Not directly exploitable in isolation, but if any upstream proxy (SSO/edge auth) appends its own `Authorization` header behind a client-supplied one, the server will silently honour the wrong one. Strict APIs reject ambiguous auth outright.
- **Likely root cause:** Default Go `r.Header.Get("Authorization")` returns the first value. Fix: check `len(r.Header.Values("Authorization")) <= 1` before parsing.

## 17. CRLF in resource fields is stored verbatim (Low, log injection)

- **Test:** `tests/test_security_pentest.py::test_crlf_in_name_does_not_inject_response_header`
- **Expected:** `\r\n` in user-supplied string fields is stripped or rejected at the boundary.
- **Actual:** `POST /api/v1/integrations` with `name: "innocent\r\nX-Injected: yes"` returns `201` and the name is stored, and read back, with the embedded CRLF intact. The HTTP layer correctly does not turn it into a response header, but the value would corrupt log lines, webhook payloads, or any downstream consumer that interpolates the name into a line-oriented format.
- **Impact:** Log injection (faking log entries, splitting alerts), and any downstream consumer that writes the value into headers (notifications, webhooks) becomes vulnerable to header injection without the API server itself being directly exploitable.
- **Likely root cause:** No input sanitisation on string fields. Fix: strip or reject `\r` / `\n` / `\x00` in the DTO validator.

---

## Positive findings (pinned as passing tests)

These categories are currently safe; passing tests in `tests/test_security_pentest.py` pin the boundary so a regression flips them:

- **No undocumented routes reachable**: every probed candidate (`/debug/pprof/`, `/debug/vars`, `/metrics`, `/admin`, `/internal`, `/api/v1/users`, `/api/v1/tenants`, `/api/v2/integrations`, `/health`, `/healthz`, `/livez`, `/readyz`, `/.git/config`, `/.env`) returns `404`.
- **No `Server` / `X-Powered-By` header**: no version disclosure.
- **No CORS reflection**: `Origin: http://evil.example` is not echoed.
- **`X-HTTP-Method-Override` is ignored**: `GET` requests with the header stay as `GET`, no auth-method bypass.
- **Host header is not echoed** into responses, no open-redirect / cache-poisoning vector.
- **Basic auth comparison is approximately constant-time**: valid-user-bad-password vs unknown-user differ by ~1 ms (under the 5 ms threshold), so user enumeration via timing is not feasible.

---

## Observation, service stability under sustained writes

Not a defect with a clean repro, but worth flagging. While running heavier test suites I noticed the service occasionally becomes unresponsive to `POST` requests while continuing to serve `GET`s normally. The Go binary stores resources in an in-memory map (see `IMAGE_ANALYSIS.md`), and the symptoms are consistent with map contention or a slow allocator pause under sustained write load. In CI this is invisible because each run starts from a fresh container, but on a long-lived deployment it would translate to write-path latency spikes. Worth a closer look at the storage layer before this ships.

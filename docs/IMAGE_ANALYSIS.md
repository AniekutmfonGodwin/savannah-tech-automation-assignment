# Docker Image Analysis

This document records the deeper investigation performed against `infralightio/test-integration-api`. The goal is to show how the test strategy was informed by the implementation surface, not only by black-box endpoint behavior.

## Image Metadata

- Image tag: `infralightio/test-integration-api:latest`
- Pinned digest used by Docker Compose: `sha256:c4766563ad1c47e242af1cef69644bf8dd6a22d34e6c27e96a15560368586705`
- Image ID observed locally: `sha256:ac316eef042eb59f37428f11c2ed2397433011f3d8a55c2031b96efb1348318c`
- Created: `2024-11-25T22:03:35Z`
- OS/architecture: `linux/arm64`
- Working directory: `/app`
- Command: `./main`
- Exposed port: `8080/tcp`

The image is intentionally minimal. It contains Alpine Linux, BusyBox, and a single executable at `/app/main`. No Go source files are shipped in the runtime image.

## Binary and Framework Evidence

Although source files are not present, the Go binary includes module metadata, symbol names, source path references, struct tags, and embedded Swagger content.

Observed module/dependency evidence:

- Module path: `testing-api`
- Web framework: `github.com/gin-gonic/gin v1.10.0`
- Swagger integration: `github.com/swaggo/gin-swagger v1.6.0`
- Validator dependency: `github.com/go-playground/validator/v10 v10.20.0`
- Auth implementation: Gin BasicAuth, evidenced by `github.com/gin-gonic/gin.BasicAuthForRealm`

Observed application source path references embedded in the binary:

- `/app/main.go`
- `/app/controller/controller.go`
- `/app/controller/integrations.go`
- `/app/controller/assets.go`
- `/app/docs/docs.go`

Observed controller symbols:

- `testing-api/controller.(*Controller).CreateIntegration`
- `testing-api/controller.(*Controller).ListIntegrations`
- `testing-api/controller.(*Controller).GetIntegration`
- `testing-api/controller.(*Controller).UpdateIntegration`
- `testing-api/controller.(*Controller).DeleteIntegration`
- `testing-api/controller.(*Controller).CreateAsset`
- `testing-api/controller.(*Controller).ListAssets`
- `testing-api/controller.(*Controller).GetAsset`
- `testing-api/controller.(*Controller).UpdateAsset`
- `testing-api/controller.(*Controller).DeleteAsset`
- `testing-api/controller.(*Controller).GenUUID`

Observed in-memory datastore type hints:

- `*map[string]*model.Integration`
- `*map[string]*model.Asset`

This strongly suggests the service stores resources in process memory using global or controller-owned maps keyed by ID.

## Runtime Route Evidence

Container startup logs reveal the runtime routes:

```text
POST   /api/v1/assets
DELETE /api/v1/assets/:id
GET    /api/v1/assets
PATCH  /api/v1/assets
GET    /api/v1/assets/:id
GET    /api/v1/integrations
POST   /api/v1/integrations
GET    /api/v1/integrations/:id
PUT    /api/v1/integrations/:id
DELETE /api/v1/integrations/:id
GET    /swagger/*any
```

The live Swagger document instead declares `PUT /api/v1/integrations` without an ID path parameter. That mismatch is not just a test assertion; it is visible by comparing generated docs from `/app/docs/docs.go` with Gin's actual registered route table.

## Model and Validation Evidence

The binary exposes JSON tags for the main models:

- `json:"id"`
- `json:"name"`
- `json:"type"`
- `json:"description"`
- `json:"tenant_id"`
- `json:"integration_id"`

I did not find embedded `binding:"required"` tags in the binary. Combined with observed behavior, this points to missing or ineffective request validation:

- `POST /api/v1/integrations` with `{}` returns `500`.
- `POST /api/v1/integrations` with only `name` creates a resource with an empty `type`.
- `POST /api/v1/assets` accepts a nonexistent `integration_id`.

The application depends on Gin's validator stack, but the request structs appear not to use required-field validation consistently.

## Likely Root Causes

These are implementation-level hypotheses based on binary evidence plus API behavior:

- Tenant isolation is probably not enforced at lookup time. The in-memory maps appear to be keyed only by resource ID, and `Get/Delete` handlers likely fetch directly from the map without comparing `resource.TenantID` to the authenticated username.
- List handlers likely iterate over all map values without filtering by tenant. This explains why `test1` and `test2` see each other's integrations.
- Asset creation likely verifies only that a JSON body can be parsed, then stores the provided `integration_id` without checking that the referenced integration exists and belongs to the caller.
- Integration update likely has route/documentation drift. Gin registers `PUT /integrations/:id`, while Swagger declares `PUT /integrations`. The implemented update handler also appears not to persist the requested name.
- Empty list responses likely return a nil slice from Go, which JSON encodes as `null`; handlers should initialize empty slices before responding.

## How This Changed The Test Strategy

The tests are intentionally biased toward the framework and platform risks the assignment exercises:

- Contract tests compare runtime behavior with the generated Swagger document because route/docs drift is visible in the image.
- Tenant isolation tests check list, get, delete, and cross-resource creation because the implementation appears map-based and ID-centric.
- Negative tests focus on missing fields and referential integrity because request structs do not appear to enforce required fields.
- Load testing uses authenticated read traffic and records throughput/p95/error rate because the in-memory implementation should be fast, and any load failure would indicate server/runtime instability rather than cloud dependency noise.

## Inspection Commands Used

Representative commands:

```sh
docker image inspect infralightio/test-integration-api:latest
docker run --rm --entrypoint sh infralightio/test-integration-api:latest -c 'ls -la /app'
docker run --rm --entrypoint sh infralightio/test-integration-api:latest -c 'strings /app/main | grep "testing-api/controller.(\\*Controller)" | sort'
docker run --rm --entrypoint sh infralightio/test-integration-api:latest -c 'strings /app/main | grep -E "testing-api/.+\\.go|/app/.+\\.go" | sort | uniq'
docker run --rm --entrypoint sh infralightio/test-integration-api:latest -c 'strings /app/main | grep "map\\[string\\].*model" | sort | uniq'
docker logs <running-container-name>
curl -u test1:test123 http://localhost:8080/swagger/doc.json
```

## Limitation

Because the image does not include source files, this is not a source review. It is a runtime and binary-symbol analysis. The conclusions are deliberately framed as evidence-backed hypotheses unless verified directly through black-box API behavior.

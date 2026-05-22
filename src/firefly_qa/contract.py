"""OpenAPI / Swagger contract validation.

The service exposes a Swagger 2.0 document at ``/swagger/doc.json``.  We use it
as the source of truth for:

  * declared status codes per (method, path)
  * declared response body schemas per (method, path, status)
  * declared base path and resource surface

Schema validation is delegated to ``jsonschema`` with the modern ``referencing``
library so $ref pointers inside ``definitions`` resolve without triggering the
deprecation warning emitted by the legacy ``RefResolver`` API.
"""

from __future__ import annotations

from typing import Any

from jsonschema import Draft4Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT4


class OpenAPIContract:
    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = spec
        self._registry = _build_registry(spec)

    def assert_status_declared(self, method: str, path: str, status_code: int) -> None:
        responses = self._responses(method, path)
        declared = set(responses)
        assert str(status_code) in declared, (
            f"{method.upper()} {path} returned {status_code}, "
            f"but the OpenAPI spec declares only {sorted(declared)}"
        )

    def assert_response_schema(
        self,
        method: str,
        path: str,
        status_code: int,
        body: Any,
    ) -> None:
        response_contract = self._responses(method, path).get(str(status_code), {})
        schema = response_contract.get("schema")
        if schema is None:
            return

        validator = Draft4Validator(schema, registry=self._registry)
        errors = sorted(validator.iter_errors(body), key=lambda error: list(error.path))
        assert not errors, _format_schema_errors(method, path, status_code, errors)

    def declared_paths(self) -> list[str]:
        return list(self.spec.get("paths", {}))

    def declared_methods(self, path: str) -> list[str]:
        return [m.lower() for m in self.spec.get("paths", {}).get(path, {})]

    def declared_statuses(self, method: str, path: str) -> list[int]:
        return sorted(int(code) for code in self._responses(method, path))

    def _responses(self, method: str, path: str) -> dict[str, Any]:
        try:
            operation = self.spec["paths"][path][method.lower()]
        except KeyError as exc:
            raise AssertionError(f"{method.upper()} {path} is not declared in OpenAPI spec") from exc
        return operation.get("responses", {})


def parse_json_or_none(response: Any) -> Any:
    if response.status_code == 204 or not response.content:
        return None
    return response.json()


def _build_registry(spec: dict[str, Any]) -> Registry:
    # Swagger 2.0 ``$ref`` strings are of the form ``#/definitions/Foo`` — making
    # the spec itself addressable at the empty base URI lets jsonschema resolve
    # them via the modern ``referencing`` API.
    resource = Resource(contents=spec, specification=DRAFT4)
    return Registry().with_resource(uri="", resource=resource)


def _format_schema_errors(method: str, path: str, status_code: int, errors: list[Any]) -> str:
    details = "; ".join(error.message for error in errors[:5])
    return f"{method.upper()} {path} response {status_code} violates OpenAPI schema: {details}"

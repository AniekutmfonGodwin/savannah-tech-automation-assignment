#!/usr/bin/env sh
set -eu

IMAGE="${API_IMAGE:-infralightio/test-integration-api:latest}"
mkdir -p reports

{
  echo "== Docker image metadata =="
  docker image inspect "$IMAGE" --format 'image={{.Id}} created={{.Created}} os={{.Os}} arch={{.Architecture}} workdir={{.Config.WorkingDir}} cmd={{json .Config.Cmd}} exposed={{json .Config.ExposedPorts}}'
  echo

  echo "== /app contents =="
  docker run --rm --entrypoint sh "$IMAGE" -c 'ls -la /app'
  echo

  echo "== Embedded source paths =="
  docker run --rm --entrypoint sh "$IMAGE" -c 'strings /app/main | grep -aoE "(/app|testing-api)/[^[:space:]]+\\.go" | sort | uniq | head -200'
  echo

  echo "== Controller symbols =="
  docker run --rm --entrypoint sh "$IMAGE" -c 'strings /app/main | grep -aoE "testing-api/controller\\.\\(\\*Controller\\)\\.[A-Za-z0-9_-]+" | sort | uniq'
  echo

  echo "== Datastore type hints =="
  docker run --rm --entrypoint sh "$IMAGE" -c 'strings /app/main | grep -aoE "\\*map\\[string\\]\\*model\\.[A-Za-z]+" | sort | uniq'
  echo

  echo "== Request/model tags and domain errors =="
  docker run --rm --entrypoint sh "$IMAGE" -c 'strings /app/main | grep -aoE "json:\\\"[^\\\"]+\\\"|integration not found|asset not found|internal server error|Authorization Required|User can not be empty" | sort | uniq'
} | tee reports/image_inspection.txt

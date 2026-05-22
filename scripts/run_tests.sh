#!/usr/bin/env sh
set -eu

mkdir -p reports
trap 'docker compose down --remove-orphans' EXIT
docker compose up --build --abort-on-container-exit --exit-code-from tests tests

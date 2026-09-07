#!/usr/bin/env bash
set -euo pipefail
# Same official source commits as install-local-minio.ps1. No moving binary aliases.
export GOBIN="$PWD/.finai/tools/minio"
export GOTELEMETRY=off
mkdir -p "$GOBIN"
go install -p 4 github.com/minio/minio@7aac2a2c5b7c882e68c1ce017d8256be2feea27f
go install -p 4 github.com/minio/mc@77f82e18b5401a65958f1619df6ebb994634bd88
(cd "$GOBIN" && sha256sum minio mc > SHA256SUMS)

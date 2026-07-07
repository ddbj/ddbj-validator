#!/usr/bin/env bash

docker run --rm -v "$(pwd):/data" -w /data ghcr.io/ddbj/ddbj-validator:latest "$@"
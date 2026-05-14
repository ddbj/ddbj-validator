#!/usr/bin/env bash

docker run --rm -v "$(pwd):/data" -w /data ghcr.io/ddbj/ddbj-validator:0.1.0-beta "$@"
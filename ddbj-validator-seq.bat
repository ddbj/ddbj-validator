@echo off
docker run --rm -v "%cd%:/work" ghcr.io/ddbj/ddbj-validator:latest ddbj --local %*
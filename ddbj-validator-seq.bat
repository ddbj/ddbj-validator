@echo off
docker run --rm -v "%cd%:/work" ddbj-validator:0.1.0-beta ddbj --local %*
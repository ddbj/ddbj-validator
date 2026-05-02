@echo off
docker run --rm -v "%cd%:/work" bsi-validator:0.1.0-beta ddbj --local %*
@echo off
REM Lance TOUTE la suite de tests dans l image de la prod (tangier-intel:latest), qui a tous les
REM modules (solders, lightgbm...). Sur le PC, l env conda n a pas les modules Solana : 9 tests y
REM echouent pour cette seule raison. Le code est monte en lecture seule : rien n est modifie.
cd /d "%~dp0.."
docker run --rm -v "%CD%:/src:ro" -w /src -e PYTHONDONTWRITEBYTECODE=1 tangier-intel:latest python -m pytest -q -p no:cacheprovider tests/intel_tests %*

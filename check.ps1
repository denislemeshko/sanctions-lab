$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
docker compose ps
if ($LASTEXITCODE -ne 0) { throw 'Docker engine is not available' }
docker compose exec -T db psql -U researcher -d research -c 'SELECT currency, count(*), max(effective_date) FROM fx_rates GROUP BY currency;'
Get-Content -Raw verify_postgres.py | docker compose exec -T pipeline python -
if ($LASTEXITCODE -ne 0) { throw 'Database verification failed' }
docker compose -p sanctions-datalens -f vendor/datalens/docker-compose.production.yaml -f datalens.local.yaml ps

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
docker compose -p sanctions-datalens -f vendor/datalens/docker-compose.production.yaml -f datalens.local.yaml stop --timeout 60
if ($LASTEXITCODE -ne 0) { throw 'DataLens did not stop cleanly' }
docker compose stop --timeout 60
if ($LASTEXITCODE -ne 0) { throw 'Research services did not stop cleanly' }
Write-Output 'Project stopped; databases and workbooks preserved.'

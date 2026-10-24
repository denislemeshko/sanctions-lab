$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path 'vendor/datalens/docker-compose.production.yaml')) {
    throw 'Prepare official DataLens repository and run its init.sh first. See README.md.'
}
docker compose -p sanctions-datalens -f vendor/datalens/docker-compose.production.yaml -f datalens.local.yaml up -d --quiet-pull
if ($LASTEXITCODE -ne 0) { throw 'DataLens startup failed' }

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path -LiteralPath '.env')) {
    $dbSecret = [guid]::NewGuid().ToString('N')
    $readerSecret = [guid]::NewGuid().ToString('N')
    "DB_PASSWORD=$dbSecret`nREADER_PASSWORD=$readerSecret" | Set-Content -LiteralPath '.env' -Encoding ascii
}
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { throw 'Docker compose failed' }

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
function Read-Setting([string]$File, [string]$Key) {
    $line = Get-Content -LiteralPath $File | Where-Object { $_.StartsWith("$Key=") } | Select-Object -First 1
    if (-not $line) { throw "Missing setting: $Key" }
    return $line.Substring($Key.Length + 1).Trim('"').Trim("'")
}
$adminSecret = Read-Setting 'vendor/datalens/.env' 'AUTH_ADMIN_PASSWORD'
$readerSecret = Read-Setting '.env' 'READER_PASSWORD'
$databaseSecret = Read-Setting '.env' 'DB_PASSWORD'
New-Item -ItemType Directory -Path data -Force | Out-Null
@"
DataLens — локальный исследовательский проект

Открыть: http://localhost:8080
Логин: admin
Пароль: $adminSecret

Подключение PostgreSQL внутри DataLens:
Хост: db
Порт: 5432
База: research
Пользователь: datalens_reader
Пароль: $readerSecret
SSL: выключен (локальная Docker network)
Схема: public
Таблицы: fx_rates, sanctions_events, event_reactions
Витрина: dashboard_events

Администратор исследовательской базы PostgreSQL:
Хост с ноутбука: localhost
Порт с ноутбука: 55432
База: research
Пользователь: researcher
Пароль: $databaseSecret

Файл содержит локальные пароли. Не публиковать.
"@ | Set-Content -LiteralPath data/ACCESS.txt -Encoding utf8
Write-Output 'Local access instructions saved to data/ACCESS.txt'

param([Parameter(Mandatory=$true)][string]$Url, [Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference = 'Stop'
if (([uri]$Url).Scheme -ne 'https') { throw 'HTTPS required' }
Invoke-WebRequest -Uri $Url -OutFile $Destination -TimeoutSec 60 -UserAgent 'SanctionsResearch/0.1'

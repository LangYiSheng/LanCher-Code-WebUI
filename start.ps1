param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$labRoot = $PSScriptRoot
$labPython = Join-Path $labRoot '.venv\Scripts\python.exe'
if(-not (Test-Path -LiteralPath $labPython)){ throw '请先运行 .\setup.ps1' }
$env:PYTHONDONTWRITEBYTECODE='1'
Push-Location -LiteralPath $labRoot
try { & $labPython -m lab --port $Port }
finally { Pop-Location }

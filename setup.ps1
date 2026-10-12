$ErrorActionPreference = 'Stop'
$labRoot = $PSScriptRoot
$labPython = Join-Path $labRoot '.venv\Scripts\python.exe'
$wheelPath = Join-Path $labRoot 'vendor\wheels\lancher_code-0.1.0-py3-none-any.whl'
if(-not (Test-Path -LiteralPath $wheelPath)){ throw '缺少固定 SDK wheel，请恢复 vendor/wheels，不能链接原仓库。' }
$snapshot = Get-Content -Raw -LiteralPath (Join-Path $labRoot 'vendor\snapshot.json') | ConvertFrom-Json
if($snapshot.wheel_sha256 -and (Get-FileHash -Algorithm SHA256 -LiteralPath $wheelPath).Hash.ToLower() -ne $snapshot.wheel_sha256){ throw 'SDK wheel 校验失败。' }
Push-Location -LiteralPath $labRoot
try {
    if(-not (Test-Path -LiteralPath $labPython)) {
        uv venv (Join-Path $labRoot '.venv') --python 3.14
        if($LASTEXITCODE -ne 0){throw '创建环境失败'}
    }
    uv pip install --python $labPython --link-mode copy -r requirements.lock.txt
    if($LASTEXITCODE -ne 0){throw '安装依赖失败'}
    docker pull python:3.14-slim
    if($LASTEXITCODE -ne 0){ Write-Warning 'Docker 不可用，工作台可以启动，但不会在宿主机执行生成代码。' }
} finally { Pop-Location }


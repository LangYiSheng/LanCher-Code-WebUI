[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$taskProject = $PSScriptRoot
Set-Location -LiteralPath $taskProject
$taskPidPath = Join-Path $taskProject 'data\webui.pid.json'
if (Test-Path -LiteralPath $taskPidPath) {
    $taskPid = Get-Content -LiteralPath $taskPidPath -Raw | ConvertFrom-Json
    if (Get-Process -Id $taskPid.process_id -ErrorAction SilentlyContinue) {
        throw '先运行 .\stop.ps1 停止本项目服务，再更新依赖，避免 Windows 锁定正在使用的扩展模块。'
    }
}
$taskUv = Get-Command uv -ErrorAction Stop
$taskPython = Join-Path $taskProject '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    & $taskUv.Source venv --python 3.14 .venv
    if ($LASTEXITCODE -ne 0) { throw '创建独立 Python 环境失败。' }
}
$taskManifest = Get-Content -LiteralPath (Join-Path $taskProject 'vendor\snapshot.json') -Raw | ConvertFrom-Json
$taskWheel = Join-Path $taskProject $taskManifest.wheel
if ((Get-FileHash -LiteralPath $taskWheel -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskManifest.wheel_sha256) {
    throw 'SDK wheel 的 SHA256 与 vendor/snapshot.json 不一致，未安装。'
}
# 只同步本项目锁定依赖，不更新用户的 TUI 环境，不强制重装全部包。
& $taskUv.Source pip sync --python $taskPython requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw '安装锁定 Python 依赖失败。' }
# 版本号相同的 SDK 快照也必须更新，只重装这一份已校验 wheel。
& $taskUv.Source pip install --python $taskPython --no-deps --reinstall $taskWheel
if ($LASTEXITCODE -ne 0) { throw '安装固定 SDK wheel 失败。' }
& $taskUv.Source pip check --python $taskPython
if ($LASTEXITCODE -ne 0) { throw 'Python 依赖兼容性检查失败。' }
Push-Location -LiteralPath (Join-Path $taskProject 'frontend')
try {
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw '安装前端锁定依赖失败。' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw '前端构建失败。' }
} finally { Pop-Location }
Write-Output '安装完成。运行 .\start.ps1 启动 LanCher Code WebUI。'

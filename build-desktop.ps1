[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$taskProject = $PSScriptRoot
$taskBuild = Join-Path $taskProject 'data\desktop-build'
$taskPython = Join-Path $taskBuild 'venv\Scripts\python.exe'
Push-Location -LiteralPath $taskProject
try {
    $taskSnapshot = Get-Content -LiteralPath 'vendor\snapshot.json' -Raw | ConvertFrom-Json
    $taskWheel = Join-Path $taskProject $taskSnapshot.wheel
    if ((Get-FileHash -LiteralPath $taskWheel -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskSnapshot.wheel_sha256) { throw 'SDK 校验失败，未构建。' }
    if (-not (Test-Path -LiteralPath $taskPython)) { & uv venv --python 3.14 (Join-Path $taskBuild 'venv'); if ($LASTEXITCODE) { throw '创建桌面构建环境失败。' } }
    & uv pip install --python $taskPython -r desktop\requirements.txt
    if ($LASTEXITCODE) { throw '安装桌面构建依赖失败。' }
    Push-Location -LiteralPath 'frontend'
    try {
        # 桌面输出单独构建，不覆盖当前 WebUI 静态文件。
        & npm.cmd run build -- --outDir ../data/desktop-build/frontend-dist
        if ($LASTEXITCODE) { throw '桌面前端构建失败。' }
    } finally { Pop-Location }
    & $taskPython -m PyInstaller --noconfirm --clean --distpath data/desktop-build/dist --workpath data/desktop-build/pyinstaller desktop/LanCherCodeDesktop.spec
    if ($LASTEXITCODE) { throw '桌面打包失败。' }
    $taskExe = Join-Path $taskBuild 'dist\LanCher Code Desktop\LanCher Code Desktop.exe'
    if (-not (Test-Path -LiteralPath $taskExe)) { throw '未生成桌面 EXE。' }
    Write-Output ('桌面便携版已构建：'+$taskExe)
} finally { Pop-Location }

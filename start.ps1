[CmdletBinding()]
param([ValidateRange(1024,65535)][int]$Port = 8765, [switch]$OpenBrowser)
$ErrorActionPreference = 'Stop'
$taskProject = $PSScriptRoot
$taskPython = Join-Path $taskProject '.venv\Scripts\python.exe'
$taskData = Join-Path $taskProject 'data'
$taskPidPath = Join-Path $taskData 'webui.pid.json'
$taskUrl = 'http://127.0.0.1:'+$Port
if (-not (Test-Path -LiteralPath $taskPython)) { throw '尚未安装；先运行 .\setup.ps1。' }
if (-not (Test-Path -LiteralPath (Join-Path $taskProject 'frontend\dist\index.html'))) { throw '前端尚未构建；先运行 .\setup.ps1。' }
if (Test-Path -LiteralPath $taskPidPath) {
    $taskExisting = Get-Content -LiteralPath $taskPidPath -Raw | ConvertFrom-Json
    if (Get-Process -Id $taskExisting.process_id -ErrorAction SilentlyContinue) {
        throw ('PID 记录中的服务仍运行：'+$taskExisting.process_id+'。先运行 stop.ps1 或打开原端口。')
    }
}
try {
    $taskProbe = Invoke-WebRequest -NoProxy -Uri ($taskUrl+'/api/bootstrap') -TimeoutSec 2
    throw ('端口 '+$Port+' 已有 HTTP 服务；请选择其他端口，不接管已有进程。')
} catch {
    if ($_.Exception.Message -like '*已有 HTTP 服务*') { throw }
    if ($_.Exception.Response) { throw ('端口 '+$Port+' 已有 HTTP 服务；请选择其他端口。') }
}
New-Item -ItemType Directory -Force -Path $taskData | Out-Null
$taskProcess = Start-Process -FilePath $taskPython -ArgumentList @('-m','webui','--port',"$Port") -WorkingDirectory $taskProject -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskData 'server.stdout.log') -RedirectStandardError (Join-Path $taskData 'server.stderr.log')
$taskRecord = @{process_id=$taskProcess.Id;port=$Port;python=$taskPython;project_root=$taskProject;started_utc=[DateTime]::UtcNow.ToString('o')}
$taskRecord | ConvertTo-Json | Set-Content -LiteralPath $taskPidPath -Encoding utf8
$taskReady = $false
for ($taskAttempt=0; $taskAttempt -lt 60; $taskAttempt++) {
    if ($taskProcess.HasExited) { throw '服务启动时退出，请查看 data/server.stderr.log。' }
    try {
        $taskState = Invoke-RestMethod -NoProxy -Uri ($taskUrl+'/api/bootstrap') -TimeoutSec 2
        $taskReady = $true
        break
    } catch { Start-Sleep -Milliseconds 250 }
}
if (-not $taskReady) { throw '服务未在等待时间内就绪，PID已保存，可运行stop.ps1收尾；查看data/server.stderr.log。' }
Write-Output ('LanCher Code WebUI 已启动：'+$taskUrl)
if ($OpenBrowser) { Start-Process -FilePath $taskUrl }

[CmdletBinding()]
param([switch]$Force)
$ErrorActionPreference = 'Stop'
$taskForced = $false
$taskProject = $PSScriptRoot
$taskPidPath = Join-Path $taskProject 'data\webui.pid.json'
if (-not (Test-Path -LiteralPath $taskPidPath)) { Write-Output '没有本项目的启动记录。'; return }
$taskRecord = Get-Content -LiteralPath $taskPidPath -Raw | ConvertFrom-Json
$taskProcess = Get-Process -Id $taskRecord.process_id -ErrorAction SilentlyContinue
if (-not $taskProcess) { Remove-Item -LiteralPath $taskPidPath; Write-Output '已记录的进程已经退出。'; return }
# 核验实际可执行文件和启动模块，PID 被复用时不能终止无关服务。
$taskNative = Get-CimInstance Win32_Process -Filter ('ProcessId = '+[int]$taskRecord.process_id)
$taskExpected = (Resolve-Path -LiteralPath (Join-Path $taskProject '.venv\Scripts\python.exe')).Path
if ($taskRecord.project_root -ne $taskProject -or $taskNative.ExecutablePath -ne $taskExpected -or $taskNative.CommandLine -notmatch '(?i)-m\s+webui\b') {
    throw 'PID记录与实际进程不匹配；未发送关闭指令，也未终止进程。'
}
$taskUrl = 'http://127.0.0.1:'+([int]$taskRecord.port)
try { Invoke-RestMethod -Method Post -Uri ($taskUrl+'/api/shutdown') -TimeoutSec 30 | Out-Null }
catch { Write-Warning '优雅关闭请求未确认，将继续等待已经启动的服务退出。' }
try { Wait-Process -Id $taskRecord.process_id -Timeout 30 -ErrorAction Stop }
catch {
    if (-not $Force) { throw '服务尚未退出，保留PID记录。检查日志后，可显式运行stop.ps1 -Force。' }
    # 强制终止前再检查，防止等待期间PID被复用。
    $taskNative = Get-CimInstance Win32_Process -Filter ('ProcessId = '+[int]$taskRecord.process_id)
    if ($taskNative.ExecutablePath -ne $taskExpected -or $taskNative.CommandLine -notmatch '(?i)-m\s+webui\b') { throw '终止前核验不匹配；未结束进程。' }
    & taskkill.exe /PID ([int]$taskRecord.process_id) /T /F | Out-Null
    if ($LASTEXITCODE -ne 0 -and (Get-Process -Id $taskRecord.process_id -ErrorAction SilentlyContinue)) { throw '已核验的服务进程树未能终止，保留PID记录。' }
    Wait-Process -Id $taskRecord.process_id -Timeout 10 -ErrorAction SilentlyContinue
    $taskForced = $true
}
Remove-Item -LiteralPath $taskPidPath
if ($taskForced) { Write-Output '已强制终止本项目服务进程树；未确认SDK优雅收尾，请在重启后检查中断会话。' } else { Write-Output 'LanCher Code WebUI 已停止；SDK会话与托管进程已通过服务关闭流程收尾。' }

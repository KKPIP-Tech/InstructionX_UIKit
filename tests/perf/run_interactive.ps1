# 位置参数：脚本路径、超时秒数、日志标签、--、测试参数。
if ($args.Count -lt 1) {
    throw "用法：run_interactive.ps1 <脚本> [超时秒数] [标签] [-- <测试参数>]"
}
$Script = [string]$args[0]
$TimeoutSeconds = if ($args.Count -ge 2) { [double]$args[1] } else { 1800 }
$Tag = if ($args.Count -ge 3) { [string]$args[2] } else { "run" }
$Arguments = if ($args.Count -gt 4) { $args[4..($args.Count - 1)] } else { @() }

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$scriptPath = (Resolve-Path $Script).Path
$rootPrefix = $root.TrimEnd("\") + "\"
if (-not $scriptPath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "只允许运行仓库内的 Python 脚本"
}
$relative = $scriptPath.Substring($rootPrefix.Length)
if ($TimeoutSeconds -le 0) {
    throw "TimeoutSeconds 必须大于 0"
}
$python = Join-Path $root ".venv\Scripts\python.exe"
$sha = (git -C $root rev-parse uniform_style).Trim()
$safeTag = $Tag -replace '[^\w.-]', '_'
$destination = Join-Path $root "temp\performance\$sha\interactive"
New-Item -ItemType Directory -Path $destination -Force | Out-Null
$log = Join-Path $destination "$safeTag.log"
$resultPath = "$log.result.json"
Remove-Item -Path $resultPath -Force -ErrorAction SilentlyContinue
$argumentList = @(
    (Join-Path $root "tests\perf\run_interactive.py"),
    "--child", "--log", $log, "--timeout", [string]$TimeoutSeconds,
    "--", $relative
)
if ($Arguments) {
    $argumentList += $Arguments
}
$quoted = $argumentList | ForEach-Object { '"' + ($_ -replace '"', '\"') + '"' }
$taskArguments = $quoted -join " "
$name = "InstructionX_UIKit_Validation_$PID"
try {
    $action = New-ScheduledTaskAction -Execute $python -Argument $taskArguments -WorkingDirectory $root
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    $task = New-ScheduledTask -Action $action -Principal $principal
    Register-ScheduledTask -TaskName $name -InputObject $task -Force -ErrorAction Stop | Out-Null
    Start-ScheduledTask -TaskName $name -ErrorAction Stop
}
finally {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
}
$deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds + 30)
$result = $null
while ($null -eq $result) {
    if ([DateTime]::UtcNow -ge $deadline) {
        throw "交互测试没有返回退出结果: $resultPath"
    }
    if (Test-Path $resultPath) {
        try {
            $candidate = [System.IO.File]::ReadAllText($resultPath) | ConvertFrom-Json
            if ($null -ne $candidate.returncode) {
                $result = $candidate
            }
        }
        catch [System.IO.IOException] {
            $result = $null
        }
    }
    if ($null -eq $result) {
        Start-Sleep -Milliseconds 100
    }
}
Write-Output $result
exit [int]$result.returncode

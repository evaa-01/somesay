# Builds the full recompilation pipeline (static + runtime) from the project root.
# Usage: powershell -ExecutionPolicy Bypass -File scripts\build_check.ps1 [-Clean]
param(
    [switch]$Clean,
    [string]$Config = "RelWithDebInfo"
)

$root = Split-Path $PSScriptRoot -Parent           # project folder (scripts\..)
$log  = Join-Path $root "logs\build.txt"

# Ensure log directory exists
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null

# Truncate / create log file fresh
[System.IO.File]::WriteAllText($log, "", [System.Text.Encoding]::UTF8)

$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
Set-Location $root

function Write-ToLogAndConsole {
    param([string]$line)
    Add-Content -Path $log -Value "$line`n" -Encoding UTF8
    Write-Host $line
}

$ok = $true
$errorLines = @()

# Step 1: static pipeline (splat -> N64Recomp)
Write-ToLogAndConsole "=== build_check.ps1 $(Get-Date -Format 'yyyy-MM-dd HH:mm') Clean=$Clean ==="
Write-ToLogAndConsole "[1/2] Static pipeline ..."
$staticOut = & "$root\scripts\rebuild.ps1" 2>&1
if ($LASTEXITCODE -ne 0) { $ok = $false }
foreach ($line in $staticOut) { Write-ToLogAndConsole $line }
# Check for failure indicators from rebuild output
$fullStatic = $staticOut -join "`n"
if ($fullStatic -match 'exit code: [1-9]' -or $fullStatic -match '\[Error\]') { $ok = $false }

# Step 2: runtime build (clang-cl + Ninja) — only if step 1 succeeded
if ($ok) {
    Write-ToLogAndConsole "[2/2] Runtime build ..."
    $runtimeArgs = @($Config)
    if ($Clean) { $runtimeArgs += "-Clean" }
    # Save current error preference to restore after build.ps1
    $savedEAP = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $runtimeOut = & "$root\runtime\build.ps1" @runtimeArgs 2>&1
    $runtimeExitCode = $LASTEXITCODE
    $ErrorActionPreference = $savedEAP
    foreach ($line in $runtimeOut) { Write-ToLogAndConsole $line }
    if ($runtimeExitCode -ne 0) { $ok = $false }
}

$elapsed = [math]::Round($stopwatch.Elapsed.TotalSeconds, 1)

if ($ok) {
    Write-ToLogAndConsole "=== DONE in ${elapsed}s ==="
    Write-Host "`nBUILD OK (${elapsed} s)" -ForegroundColor Green
} else {
    # Collect error lines from full log for summary display
    $allLog = Get-Content $log
    $errorLines = @($allLog | Where-Object { $_ -match 'error:|subcommand failed|\[Error\]' })
    Write-ToLogAndConsole "=== FAILED at $($stopwatch.Elapsed.TotalSeconds / 60) min ==="
    Write-Host "`nBUILD FAILED" -ForegroundColor Red
    $errHead = $errorLines | Select-Object -Unique -First 5
    if ($errHead.Count -gt 0) { foreach ($e in $errHead) { Write-Host $e } }
    else { Write-Host "No error lines found; see $log" }
}

# Starts the game with its console output saved, watches it for a while and says what happened:
#   RUNNING - still alive and still printing (or its frame counter in the window title advances)
#   HANG    - alive, but the frame counter stands still (or, without a counter, no new output for -Quiet s). CPU tells:
#             BUSY (a core or more in use) = a thread spins in a loop -> hang_report.ps1, extra_hooks candidate
#             IDLE (almost no CPU)         = everything waits (missing event/interrupt, deadlock) -> hang_report.ps1
#             + the frame counter from the window title ("frame <n>"), if the runtime shows one: advancing / NOT advancing
#   EXIT    - the process ended: exit code, how long it ran, the last lines of its output
#   pwsh -File scripts\run_watch.ps1 [-ArgLine "--rom ..\..\rom\game.z64"] [-Seconds 30] [-Quiet 10] [-Exe <path>]
#        [-Stop]
# The game keeps running after the report (so you can take a screenshot or a backtrace with its PID); -Stop ends it
# (by PID). Output: stdout/stderr in logs\watch_<time>_stdout.txt / _stderr.txt, the report also in logs\watch_<time>.txt.
# Default -Exe: runtime\build\<project folder name>.exe. Note: a program's output to a file can be buffered, so "no
# new output" alone is not proof of a hang; the CPU and "responding" values help, and hang_report.ps1 decides.
# Generic: no game values. Exit code: 0 RUNNING, 2 HANG, 3 EXIT, 1 error.
param(
    [string]$Exe = "",
    [string]$ArgLine = "",
    [int]$Seconds = 30,
    [int]$Quiet = 10,
    [string]$LogDir = "",
    [int]$TailLines = 15,
    [switch]$Stop
)
$ErrorActionPreference = "Stop"
$project = Split-Path $PSScriptRoot -Parent
if (-not $Exe) { $Exe = Join-Path $project ("runtime\build\" + (Split-Path $project -Leaf) + ".exe") }
if (-not $LogDir) { $LogDir = Join-Path $project "logs" }
if (-not (Test-Path $Exe)) { Write-Host "Program not found: $Exe (use -Exe)."; exit 1 }
$Exe = (Resolve-Path $Exe).Path
New-Item -ItemType Directory -Force $LogDir | Out-Null
$stamp = "{0:yyyyMMdd_HHmmss}" -f (Get-Date)
$out = Join-Path $LogDir "watch_${stamp}_stdout.txt"
$err = Join-Path $LogDir "watch_${stamp}_stderr.txt"
$report = Join-Path $LogDir "watch_${stamp}.txt"

$start = @{ FilePath = $Exe; WorkingDirectory = (Split-Path $Exe -Parent); PassThru = $true
            RedirectStandardOutput = $out; RedirectStandardError = $err }
if ($ArgLine) { $start.ArgumentList = $ArgLine }
$p = Start-Process @start
$t0 = Get-Date
Write-Host "Started $(Split-Path $Exe -Leaf) $ArgLine  (PID $($p.Id)), watching for $Seconds s..."

function OutSize { (Get-Item $out -ErrorAction SilentlyContinue).Length + (Get-Item $err -ErrorAction SilentlyContinue).Length }
$lastSize = -1; $lastChange = Get-Date
while (((Get-Date) - $t0).TotalSeconds -lt $Seconds) {
    if ($p.HasExited) { break }
    $size = OutSize
    if ($size -ne $lastSize) { $lastSize = $size; $lastChange = Get-Date }
    Start-Sleep -Milliseconds 500
}
$p.Refresh()
$lines = @()
if (-not $p.HasExited) {
    # CPU over 3 seconds, in "cores" (1.0 = one core fully busy)
    # frame counter from the window title ("frame <n>", if the runtime shows one), read before and after the 3 s
    function TitleFrame { $p.Refresh(); if ($p.MainWindowTitle -match '(?i)frame\s+(\d+)') { [int64]$Matches[1] } else { $null } }
    $fr0 = TitleFrame
    $c1 = $p.TotalProcessorTime.TotalSeconds; Start-Sleep 3; $p.Refresh()
    $fr1 = TitleFrame
    if (-not $p.HasExited) {
        $cores = ($p.TotalProcessorTime.TotalSeconds - $c1) / 3
        if ((OutSize) -ne $lastSize) { $lastChange = Get-Date }
        $quietFor = [int]((Get-Date) - $lastChange).TotalSeconds
        $kind = if ($cores -ge 0.5) { "BUSY" } else { "IDLE" }
        # the frame counter decides when there is one (a game may run silently); otherwise console silence = HANG
        $state = if ($null -ne $fr0 -and $null -ne $fr1) { if ($fr1 -gt $fr0) { "RUNNING" } else { "HANG" } }
                 elseif ($quietFor -ge $Quiet) { "HANG" } else { "RUNNING" }
        $lines += "$state  PID $($p.Id), running $([int]((Get-Date) - $t0).TotalSeconds) s, no new output for $quietFor s"
        $lines += ("CPU: {0:N2} cores -> {1}   window responding: {2}   window title: '{3}'" -f $cores, $kind, $p.Responding, $p.MainWindowTitle)
        $lines += ("threads: {0}   memory: {1:N0} MB" -f $p.Threads.Count, ($p.WorkingSet64 / 1MB))
        if ($null -ne $fr0 -and $null -ne $fr1) {
            if ($fr1 -gt $fr0) { $lines += ("frame counter {0} -> {1} in 3 s: advancing ({2:N0} frames/s)" -f $fr0, $fr1, (($fr1 - $fr0) / 3)) }
            else { $lines += "frame counter $fr0 -> $fr1 in 3 s: NOT advancing (game loop stuck at frame $fr1)" }
        }
        if ($state -eq "HANG") {
            $lines += "next: screenshot of the window, then ONE backtrace: scripts\hang_report.ps1 -ProcessId $($p.Id) (the game ends after it)"
        }
    }
}
if ($p.HasExited) {
    $state = "EXIT"
    $code = $p.ExitCode
    # Windows crash codes arrive as negative numbers (PowerShell: 0xFFFFFFFF is -1, so no -band here)
    $hex = "0x{0:X8}" -f $(if ($code -lt 0) { [int64]$code + 4294967296 } else { [int64]$code })
    $known = @{ "0xC0000005" = "access violation (crash)"; "0xC0000409" = "stack buffer overrun / abort / fast-fail";
                "0xC00000FD" = "stack overflow"; "0xC0000374" = "heap corruption"; "0x80000003" = "breakpoint (assert)";
                "0xE06D7363" = "unhandled C++ exception"; "0xC000001D" = "illegal instruction" }
    $what = if ($known.ContainsKey($hex)) { " = " + $known[$hex] } elseif ($code -eq 0) { " (normal end)" } else { "" }
    $lines += "EXIT  after $([int]($p.ExitTime - $t0).TotalSeconds) s, exit code $code ($hex)$what"
}
$lines += "logs: $out"
$lines += "      $err"
foreach ($f in @($out, $err)) {
    $tail = @(Get-Content $f -Tail $TailLines -ErrorAction SilentlyContinue)
    if ($tail.Count) { $lines += "--- last $($tail.Count) lines of $(Split-Path $f -Leaf):"; $lines += $tail | ForEach-Object { "  $_" } }
}
if ($Stop -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force; $lines += "stopped (PID $($p.Id))" }
$lines | Set-Content $report
$lines | ForEach-Object { Write-Host $_ }
switch ($state) { "RUNNING" { exit 0 } "HANG" { exit 2 } default { exit 3 } }

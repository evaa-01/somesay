# Backtrace of a hanging game in one step, mapped back to MIPS addresses, with a verdict per game thread.
#   pwsh -File scripts\hang_report.ps1 -ProcessId <pid>  [-FuncsDir RecompiledFuncs] [-Lldb <path>]
# What it does:
#   1. lldb attaches to the running game, prints every thread's backtrace and detaches.
#      NOTE: on Windows the game ENDS right after this (lldb batch attach) - you get one backtrace per run.
#   2. Every frame that lies in a generated file (funcs_*.c in -FuncsDir) is mapped to its MIPS address: the
#      "// 0x8xxxxxxx:" comment N64Recomp writes above each line.
#   3. Verdict per thread that runs game code:
#        WAITS - an OS/runtime wait (WaitFor..., Sleep..., condition variable...) is above the game code: fine.
#        BUSY  - no wait above the game code: the thread spins = busy-wait candidate (BLUEPRINT phase 5, extra_hooks).
# Output: a short summary here; the raw lldb output in logs\hang_<time>.txt. Exit code 0 = report written, 1 = error.
param(
    [Parameter(Mandatory)][int]$ProcessId,
    [string]$FuncsDir = (Join-Path (Split-Path $PSScriptRoot -Parent) "RecompiledFuncs"),
    [string]$Lldb = "C:\Program Files\LLVM\bin\lldb.exe",
    [string]$LogDir = (Join-Path (Split-Path $PSScriptRoot -Parent) "logs")
)
$ErrorActionPreference = "Stop"
if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) { Write-Host "No process with PID $ProcessId."; exit 1 }
if (-not (Test-Path $Lldb)) { Write-Host "lldb not found at $Lldb (use -Lldb)."; exit 1 }
if (-not (Test-Path $FuncsDir)) { Write-Host "Generated code folder not found: $FuncsDir (use -FuncsDir)."; exit 1 }
New-Item -ItemType Directory -Force $LogDir | Out-Null
$log = Join-Path $LogDir ("hang_{0:yyyyMMdd_HHmmss}.txt" -f (Get-Date))

Write-Host "Attaching to PID $ProcessId (the game will end afterwards - one backtrace per run)..."
& $Lldb -b -p $ProcessId -o "thread backtrace all" -o "process detach" *> $log
$raw = Get-Content $log

# --- parse threads and frames -------------------------------------------------------------------------------------
$waitPattern = 'NtWaitFor|WaitFor(Single|Multiple)Object|SleepConditionVariable|SleepEx|NtDelayExecution|RtlSleep|ZwWait|' +
               'WaitOnAddress|RtlWaitOnAddress|GetQueuedCompletionStatus|NtRemoveIoCompletion|condition_variable|' +
               'semaphore|_Cnd_wait|_Mtx_lock|osRecvMesg|block_self|pause_self|yield_self|wait_for'
$threads = @(); $cur = $null
foreach ($line in $raw) {
    if ($line -match '^\s*\*?\s*thread #(\d+)') {
        $cur = [pscustomobject]@{ Id = [int]$Matches[1]; Frames = New-Object System.Collections.ArrayList }
        $threads += $cur; continue
    }
    if ($cur -and $line -match 'frame #(\d+): 0x[0-9a-fA-F]+ ([^`]+)`(.*)$') {
        $n = [int]$Matches[1]; $module = $Matches[2]; $rest = $Matches[3]; $file = $null; $ln = 0
        if ($rest -match ' at ([^:\s]+):(\d+)') { $file = $Matches[1]; $ln = [int]$Matches[2] }
        $func = ($rest -split '[\( ]', 2)[0]
        [void]$cur.Frames.Add([pscustomobject]@{ N = $n; Module = $module; Func = $func; File = $file; Line = $ln })
    }
}
# lldb lists the stopped thread twice (summary at the top); keep the first copy that has frames
$threads = $threads | Where-Object { $_.Frames.Count -gt 0 } | Group-Object Id | ForEach-Object { $_.Group[0] }

# --- map generated-code frames to MIPS addresses --------------------------------------------------------------------
$cache = @{}
function Get-Mips($file, $ln) {
    if (-not $file -or $ln -le 0) { return $null }
    $name = Split-Path $file -Leaf
    if (-not $cache.ContainsKey($name)) {
        $hit = Get-ChildItem -Path $FuncsDir -Filter $name -File -ErrorAction SilentlyContinue | Select-Object -First 1
        $cache[$name] = if ($hit) { @(Get-Content $hit.FullName) } else { $null }
    }
    $src = $cache[$name]
    if (-not $src) { return $null }
    for ($i = [Math]::Min($ln, $src.Count) - 1; $i -ge 0; $i--) {
        if ($src[$i] -match '//\s*0x([0-9A-Fa-f]{8}):') { return "0x" + $Matches[1].ToUpper() }
    }
    return $null
}

# Fallback for builds without debug info (no file:line in the backtrace): find the function by name in the generated
# files and report its START address (the first "// 0x8...:" comment after its definition).
$funcStart = @{}
foreach ($f in Get-ChildItem -Path $FuncsDir -Filter "funcs_*.c" -File -ErrorAction SilentlyContinue) {
    $name = $null
    foreach ($l in Get-Content $f.FullName) {
        if ($l -match '^\s*(?:RECOMP_FUNC\s+)?void\s+(\w+)\s*\(') { $name = $Matches[1]; continue }
        if ($name -and $l -match '//\s*0x([0-9A-Fa-f]{8}):') { $funcStart[$name] = "0x" + $Matches[1].ToUpper(); $name = $null }
    }
}
foreach ($t in $threads) {
    foreach ($fr in $t.Frames) {
        $m = Get-Mips $fr.File $fr.Line
        if (-not $m -and $funcStart.ContainsKey($fr.Func)) { $m = "$($funcStart[$fr.Func]) (function start)" }
        $fr | Add-Member -NotePropertyName Mips -NotePropertyValue $m
    }
}

$exeFrames = @($threads | ForEach-Object { $_.Frames } | Where-Object { $_.Module -like "*.exe" })
if ($exeFrames.Count -and -not @($exeFrames | Where-Object { $_.Func }).Count) {
    Write-Host "The game's frames have no function names: the exe was built without debug info."
    Write-Host "Rebuild the runtime as RelWithDebInfo (a .pdb next to the exe), then run this again. Raw backtrace: $log"
    exit 1
}

$report = @(); $other = 0
foreach ($t in $threads) {
    $game = @($t.Frames | Where-Object { $_.Mips })
    if ($game.Count -eq 0) { $other++; continue }
    $top = $game[0]
    $above = @($t.Frames | Where-Object { $_.N -lt $top.N })
    $wait = $above | Where-Object { $_.Func -match $waitPattern } | Select-Object -First 1
    $chain = ($game | Select-Object -First 4 | ForEach-Object { "$($_.Func)@$($_.Mips)" }) -join " <- "
    $report += [pscustomobject]@{
        Thread  = $t.Id
        Verdict = if ($wait) { "WAITS" } else { "BUSY" }
        Game    = "$($top.Func) at MIPS $($top.Mips)"
        Detail  = if ($wait) { "waits in $($wait.Func)" } else { "no OS wait above the game code" }
        Chain   = $chain
    }
}

Write-Host ""
Write-Host "Threads: $($threads.Count) total, $($report.Count) running game code, $other runtime/OS only."
foreach ($r in $report | Sort-Object Verdict, Thread) {
    Write-Host ("  thread #{0,-3} {1,-5} {2}  ({3})" -f $r.Thread, $r.Verdict, $r.Game, $r.Detail)
    Write-Host ("               calls: {0}" -f $r.Chain)
}
$busy = @($report | Where-Object Verdict -eq "BUSY")
if ($busy.Count) {
    Write-Host ""
    Write-Host "BUSY threads spin without an OS call: busy-wait candidates (BLUEPRINT phase 5). Look at the MIPS code at"
    Write-Host "those addresses before writing any hook."
}
Write-Host "Raw backtrace: $log"
exit 0

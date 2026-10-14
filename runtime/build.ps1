# Builds runtime\\build\\somesay.exe with clang-cl + Ninja.
# Usage: powershell -ExecutionPolicy Bypass -File runtime\\build.ps1 [-Config Debug|RelWithDebInfo|Release] [-Clean]
param(
    [string]$Config = "RelWithDebInfo",
    [switch]$Clean
)
$ErrorActionPreference = "Stop"

$vsRoot = "C:\\Program Files\\Microsoft Visual Studio\\18\\Community"
$vcvars = "$vsRoot\\VC\\Auxiliary\\Build\\vcvars64.bat"
$ninja  = "$vsRoot\\Common7\\IDE\\CommonExtensions\\Microsoft\\CMake\\Ninja\\ninja.exe"
$llvm   = "C:\\Program Files\\LLVM\\bin"

# Import the VS developer environment (INCLUDE, LIB, PATH...) into this PowerShell session.
cmd /c "`"$vcvars`" >nul && set" | ForEach-Object {
    if ($_ -match '^([^=]+)=(.*)$') { Set-Item -Path "env:$($matches[1])" -Value $matches[2] }
}
$env:PATH = "$llvm;" + $env:PATH

$src = $PSScriptRoot
$build = Join-Path $src "build"

if ($Clean -and (Test-Path $build)) { Remove-Item -Recurse -Force $build }

# Patches to the checkouts in tools/: rt64-*.patch for RT64, recompfrontend-*.patch for RecompFrontend.
# When patches are added later, they go into runtime\\patches\\.
$deps = Join-Path $src "../tools"
$patchTargets = @{ "rt64" = (Join-Path $deps "rt64"); "recompfrontend" = (Join-Path $deps "RecompFrontend");
    "n64modernruntime" = (Join-Path $deps "N64ModernRuntime"); "n64recomp" = (Join-Path $deps "N64ModernRuntime\\N64Recomp") }
foreach ($prefix in $patchTargets.Keys) {
    $repo = $patchTargets[$prefix]
    $patchDir = Join-Path $src "patches"
    if (-not (Test-Path $patchDir)) { continue }
    foreach ($patch in Get-ChildItem (Join-Path $patchDir "$prefix-*.patch")) {
        $ErrorActionPreference = "Continue"
        git -C $repo apply --reverse --check $patch.FullName 2>$null
        $applied = ($LASTEXITCODE -eq 0)
        if (-not $applied) { git -C $repo apply $patch.FullName }
        $ok = $applied -or ($LASTEXITCODE -eq 0)
        $ErrorActionPreference = "Stop"
        if (-not $ok) { Write-Error "Could not apply $($patch.Name) to $repo" }
        if (-not $applied) { "Applied $($patch.Name) to $repo" }
    }
}

cmake -S $src -B $build -G Ninja "-DCMAKE_MAKE_PROGRAM=$ninja" `
    -DCMAKE_C_COMPILER=clang-cl -DCMAKE_CXX_COMPILER=clang-cl "-DCMAKE_BUILD_TYPE=$Config"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

cmake --build $build
exit $LASTEXITCODE

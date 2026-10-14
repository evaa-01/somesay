$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent   # project folder (scripts\..)
python -m splat split (Join-Path $root "splat\somesay.yaml") | Out-Null
python scripts\splat_to_toml.py
Copy-Item symbols.splat.toml symbols.toml -Force
python scripts\update_stubs.py | Select-Object -First 1
# Clear old output: N64Recomp doesn't delete funcs_N.c files from earlier runs, and the runtime
# build compiles every .c in the folder (stale files call functions by outdated names).
if (Test-Path RecompiledFuncs) { Remove-Item RecompiledFuncs\* -Force }
& (Join-Path $root "tools\N64Recomp\build\Release\N64Recomp.exe") config.toml
"exit code: $LASTEXITCODE"

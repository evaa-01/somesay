# Clones the tool checkouts into the project's tools\ folder at the exact commits the reference project (adam) uses,
# so the patches in reference\adam\runtime\patches\ fit. Run from anywhere:
#   pwsh -ExecutionPolicy Bypass -File tools\get_tools.ps1            (core: 4 checkouts)
#   pwsh -ExecutionPolicy Bypass -File tools\get_tools.ps1 -References (also the two reference ports, read-only examples)
# Existing checkouts are left alone (it only reports their commit).
param([switch]$References)
$ErrorActionPreference = "Stop"
$tools = $PSScriptRoot

$repos = @(
    @{ Name = "N64Recomp";        Url = "https://github.com/N64Recomp/N64Recomp";        Commit = "ffb39cdad1da5de07eaaa48bd1db4a89a7986771" },
    @{ Name = "N64ModernRuntime"; Url = "https://github.com/N64Recomp/N64ModernRuntime"; Commit = "cdf5abbd5026fef5c364c676e4667c45e42b6863" },
    @{ Name = "rt64";             Url = "https://github.com/rt64/rt64";                  Commit = "8bd2cf1530c17ce8c3489eb47671ee0da2f8319d" },
    @{ Name = "RecompFrontend";   Url = "https://github.com/N64Recomp/RecompFrontend";   Commit = "b1a1477c6556aeb7ed45defbfb5924f721efebc1" }
)
if ($References) {
    $repos += @{ Name = "Zelda64Recomp"; Url = "https://github.com/Zelda64Recomp/Zelda64Recomp"; Commit = "b65c482ed672258eb684ab94a4e8c8aa662615ee" }
    $repos += @{ Name = "BanjoRecomp";   Url = "https://github.com/BanjoRecomp/BanjoRecomp";     Commit = "dbd52154bc1e00e56867b1fac94a8f907052f41b" }
}

foreach ($r in $repos) {
    $dir = Join-Path $tools $r.Name
    if (Test-Path (Join-Path $dir ".git")) {
        Write-Host "$($r.Name): already there at $(git -C $dir rev-parse --short HEAD) (wanted $($r.Commit.Substring(0,7)))"
        continue
    }
    Write-Host "$($r.Name): cloning..."
    git clone $r.Url $dir
    if ($LASTEXITCODE -ne 0) { throw "clone of $($r.Name) failed" }
    git -C $dir checkout --quiet $r.Commit
    if ($LASTEXITCODE -ne 0) { throw "checkout $($r.Commit) in $($r.Name) failed" }
    git -C $dir submodule update --init --recursive
    if ($LASTEXITCODE -ne 0) { throw "submodules of $($r.Name) failed" }
    Write-Host "$($r.Name): at $(git -C $dir rev-parse --short HEAD)"
}
Write-Host "done"

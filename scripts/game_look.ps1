# Looks at the game window: takes a picture of ONLY that window (also when other windows lie over it), says what kind
# of picture it is and reads its text with the local Windows OCR. Nothing is uploaded; never the whole screen.
#   pwsh -File scripts\game_look.ps1 -ProcessId <pid> [-Out logs\look.png] [-NoOcr] [-OcrScale 2] [-Shots 3] [-Interval 1]
# Verdict:  BLACK   - every pixel is black (checked on all pixels): renderer not started, or the game draws nothing yet
#           FLAT    - one single colour (clear colour, no geometry)
#           PICTURE - real content; read the OCR text, then let the person look at the PNG
#           MINIMIZED / NO WINDOW - nothing to capture
# Motion (-Shots N, default 3, -Interval seconds apart): ANIMATING (pixels change between shots) or FROZEN (identical
# picture). Frame counter: if the window title contains "frame <n>", it is read at each shot -> advancing / NOT advancing
# (a frozen picture with an advancing counter = the game runs but draws the same; both stopped = the game is stuck).
# How: PrintWindow with PW_RENDERFULLCONTENT|PW_CLIENTONLY (3) on the process's largest visible window, client area
# only (no title bar). The window title is printed separately (the runtime may show state there).
# OCR: scripts\ocr.ps1 (copy it from reference\adam\scripts), run with Windows PowerShell 5.1 (it needs WinRT).
# Generic: no game values. Exit code 0 = picture taken, 1 = error / no window.
param(
    [Parameter(Mandatory)][int]$ProcessId,
    [string]$Out = "",
    [switch]$NoOcr,
    [double]$OcrScale = 2,
    [int]$Shots = 3,
    [double]$Interval = 1
)
$ErrorActionPreference = "Stop"
$project = Split-Path $PSScriptRoot -Parent
if (-not $Out) { $Out = Join-Path $project ("logs\look_{0:yyyyMMdd_HHmmss}.png" -f (Get-Date)) }
New-Item -ItemType Directory -Force (Split-Path $Out -Parent) | Out-Null
if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) { Write-Host "No process with PID $ProcessId."; exit 1 }
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Collections.Generic; using System.Runtime.InteropServices; using System.Text;
public static class GL {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  public delegate bool EnumProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc p, IntPtr l);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  // every pixel of a 32-bit BGRA image: { dark pixels (luminance < 16), brightest luminance, mean luminance, colours }
  public static double[] Stats(byte[] d, int stride, int w, int h) {
    long dark = 0; double sum = 0, max = 0; var cols = new HashSet<int>();
    for (int y = 0; y < h; y++) for (int x = 0; x < w; x++) {
      int i = y * stride + x * 4; byte b = d[i], g = d[i + 1], r = d[i + 2];
      double lum = 0.299 * r + 0.587 * g + 0.114 * b; sum += lum; if (lum > max) max = lum; if (lum < 16) dark++;
      if (cols.Count < 100000) cols.Add(((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3));
    }
    return new double[] { dark, max, sum / ((double)w * h), cols.Count };
  }
  // pixels whose colour differs by more than 24 in any channel (ignores tiny noise/dithering)
  public static long Changed(byte[] a, byte[] b, int stride, int w, int h) {
    long n = 0;
    for (int y = 0; y < h; y++) for (int x = 0; x < w; x++) {
      int i = y * stride + x * 4;
      if (Math.Abs(a[i] - b[i]) > 24 || Math.Abs(a[i + 1] - b[i + 1]) > 24 || Math.Abs(a[i + 2] - b[i + 2]) > 24) n++;
    }
    return n;
  }
  public static string Title(IntPtr h) { var s = new StringBuilder(512); GetWindowText(h, s, 512); return s.ToString(); }
  // largest visible top-level window of the process (the game window, not a console or a tooltip)
  public static IntPtr Find(uint pid) {
    IntPtr best = IntPtr.Zero; long bestArea = -1;
    EnumWindows((h, l) => {
      uint p; GetWindowThreadProcessId(h, out p);
      if (p == pid && IsWindowVisible(h)) {
        RECT r; GetClientRect(h, out r); long a = (long)(r.R - r.L) * (r.B - r.T);
        if (a > bestArea) { bestArea = a; best = h; }
      }
      return true; }, IntPtr.Zero);
    return best;
  }
}
"@
[GL]::SetProcessDPIAware() | Out-Null
$h = [GL]::Find([uint32]$ProcessId)
if ($h -eq [IntPtr]::Zero) { Write-Host "NO WINDOW - PID $ProcessId has no visible window (yet)."; exit 1 }
$title = [GL]::Title($h)
if ([GL]::IsIconic($h)) { Write-Host "MINIMIZED - window '$title' is minimized; restore it, then try again."; exit 1 }
$r = New-Object GL+RECT
[void][GL]::GetClientRect($h, [ref]$r)
$w = $r.R - $r.L; $hgt = $r.B - $r.T
if ($w -le 0 -or $hgt -le 0) { Write-Host "NO WINDOW - client area is empty ($w x $hgt)."; exit 1 }

function Grab {
    $bmp = New-Object System.Drawing.Bitmap $w, $hgt
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $hdc = $g.GetHdc()
    $ok = [GL]::PrintWindow($h, $hdc, 3)   # PW_CLIENTONLY (1) | PW_RENDERFULLCONTENT (2)
    $g.ReleaseHdc($hdc); $g.Dispose()
    if (-not $ok) { $bmp.Dispose(); return $null }
    $rect = New-Object System.Drawing.Rectangle 0, 0, $w, $hgt
    $bits = $bmp.LockBits($rect, [System.Drawing.Imaging.ImageLockMode]::ReadOnly, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
    $data = New-Object byte[] ($bits.Stride * $hgt)
    [System.Runtime.InteropServices.Marshal]::Copy($bits.Scan0, $data, 0, $data.Length)
    $stride = $bits.Stride
    $bmp.UnlockBits($bits)
    $frame = if ([GL]::Title($h) -match '(?i)\bframe\s+(\d+)') { [int64]$Matches[1] } else { $null }
    return [pscustomobject]@{ Bmp = $bmp; Data = $data; Stride = $stride; Frame = $frame; Time = Get-Date }
}

$shotsTaken = @()
for ($k = 0; $k -lt [Math]::Max(1, $Shots); $k++) {
    if ($k -gt 0) { Start-Sleep -Milliseconds ([int]($Interval * 1000)) }
    $s1 = Grab
    if (-not $s1) { Write-Host "PrintWindow failed for window '$title'."; exit 1 }
    $shotsTaken += $s1
}
$last = $shotsTaken[-1]
$last.Bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)

# --- what kind of picture (last shot, every pixel) -------------------------------------------------------------------
$st = [GL]::Stats($last.Data, $last.Stride, $w, $hgt)
$total = [double]$w * $hgt
$darkPct = 100.0 * $st[0] / $total
# BLACK only if not a single pixel is brighter than "dark" (small text on black is still a PICTURE)
$verdict = if ($st[1] -lt 16) { "BLACK" } elseif ($st[3] -le 1) { "FLAT" } else { "PICTURE" }
Write-Host ("{0}  window '{1}', {2}x{3}, dark pixels {4:N2}%, brightest {5:N0}/255, mean {6:N0}/255, colours {7}" -f `
    $verdict, $title, $w, $hgt, $darkPct, $st[1], $st[2], $st[3])

# --- motion between the shots + frame counter from the title ---------------------------------------------------------
if ($shotsTaken.Count -ge 2) {
    $changes = @()
    for ($k = 1; $k -lt $shotsTaken.Count; $k++) {
        $changes += 100.0 * [GL]::Changed($shotsTaken[$k - 1].Data, $shotsTaken[$k].Data, $last.Stride, $w, $hgt) / $total
    }
    $max = ($changes | Measure-Object -Maximum).Maximum
    $motion = if ($max -ge 0.05) { "ANIMATING" } else { "FROZEN" }
    Write-Host ("{0}  {1} shots {2} s apart, changed pixels per step: {3}" -f $motion, $shotsTaken.Count, $Interval,
        (($changes | ForEach-Object { "{0:N2}%" -f $_ }) -join ", "))
    $f0 = $shotsTaken[0].Frame; $f1 = $last.Frame
    if ($null -ne $f0 -and $null -ne $f1) {
        $secs = ($last.Time - $shotsTaken[0].Time).TotalSeconds
        if ($f1 -gt $f0) { Write-Host ("frame counter {0} -> {1}: advancing ({2:N0} frames/s)" -f $f0, $f1, (($f1 - $f0) / $secs)) }
        else { Write-Host "frame counter $f0 -> ${f1}: NOT advancing (the game loop is stuck)" }
    } else { Write-Host "frame counter: none in the window title" }
}
$shotsTaken | ForEach-Object { $_.Bmp.Dispose() }
Write-Host "image: $Out  (look at it locally; never upload it)"

if (-not $NoOcr -and $verdict -eq "PICTURE") {
    $ocr = Join-Path $PSScriptRoot "ocr.ps1"
    if (-not (Test-Path $ocr)) { $ocr = Join-Path $project "reference\adam\scripts\ocr.ps1" }
    if (-not (Test-Path $ocr)) { Write-Host "(no OCR: scripts\ocr.ps1 not found)"; exit 0 }
    $text = @(& powershell.exe -NoProfile -ExecutionPolicy Bypass -File $ocr $Out -Scale $OcrScale 2>&1)
    Write-Host "text ($($text.Count) lines, 'x y w h  text'):"
    $text | ForEach-Object { Write-Host "  $_" }
}
exit 0

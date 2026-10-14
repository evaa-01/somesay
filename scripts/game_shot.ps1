# Captures ONLY the game window to a PNG file using PrintWindow (PW_RENDERFULLCONTENT = 2).
# Usage: powershell -ExecutionPolicy Bypass -File scripts\game_shot.ps1 <pid> <out.png>
# Must not capture anything that lies over the game window. Never captures the whole screen.

param([Parameter(Mandatory)][int]$Pid, [Parameter(Mandatory)][string]$Out)
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Drawing

# Win32 API declarations.
Add-Type @"
using System; using System.Runtime.InteropServices;
public static class G {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("gdi32.dll")][return: MarshalAs(UnmanagedType.Bool)] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hwnd, IntPtr hdcBlt, uint nFlags);
  [DllImport("gdi32.dll")] public static extern IntPtr CreateCompatibleDC(IntPtr hdc);
  [DllImport("gdi32.dll")] public static extern IntPtr CreateCompatibleBitmap(IntPtr hdc, int w, int h);
  [DllImport("gdi32.dll")] public static extern IntPtr SelectObject(IntPtr hdc, IntPtr hObject);
  [DllImport("gdi32.dll")] public static extern int DeleteObject(IntPtr hObject);
  [DllImport("gdi32.dll")] public static extern bool DeleteDC(IntPtr hdc);
  [DllImport("user32.dll")] public static extern IntPtr GetDC(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr ReleaseDC(IntPtr hWnd, IntPtr hDc);
}
"@

Add-Type @"
using System; using System.Runtime.InteropServices;
public static class E {
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc proc, IntPtr lParam);
  public delegate bool EnumWindowsProc(IntPtr h, IntPtr l);
}
"@

# --- Find the window handle for this PID -----------------------------------------------

$process = Get-Process -Id $Pid -ErrorAction Stop
$pidUint = [uint32]$process.Id

$handles = @()
$callback = [E+EnumWindowsProc]::New({
    param($hWnd, $lParam)
    $foundPid = [uint32]0
    [G]::GetWindowThreadProcessId($hWnd, [ref]$foundPid) | Out-Null
    if ($foundPid -eq $pidUint) { $handles += $hWnd }
    return $true
})
[E]::EnumWindows($callback, [IntPtr]::Zero) | Out-Null

if ($handles.Count -eq 0) { Write-Error "No windows found for PID $Pid"; exit 1 }

# Pick the first visible window.
$hWnd = $null
foreach ($h in $handles) {
    if ([G]::IsWindowVisible($h)) { $hWnd = $h; break }
}
if ($hWnd -eq $null) { Write-Error "No visible window for PID $Pid"; exit 1 }

# --- Capture with PrintWindow ------------------------------------------------------------

$rect = New-Object G+RECT
[G]::GetWindowRect($hWnd, [ref]$rect) | Out-Null
$w = $rect.R - $rect.L
$hgt = $rect.B - $rect.T

$hDC = [G]::GetDC($hWnd)
$memDC = [IntPtr]::Zero
$hBmp = [IntPtr]::Zero

try {
    $memDC = [G]::CreateCompatibleDC($hDC)
    if ($memDC -eq [IntPtr]::Zero) { throw "CreateCompatibleDC failed" }

    $hBmp = [G]::CreateCompatibleBitmap($hDC, $w, $hgt)
    if ($hBmp -eq [IntPtr]::Zero) { throw "CreateCompatibleBitmap failed" }

    [G]::SelectObject($memDC, $hBmp) | Out-Null

    # PrintWindow with PW_RENDERFULLCONTENT (2): renders the window directly into our DC.
    $ok = [G]::PrintWindow($hWnd, $memDC, [uint32]2)
    if (-not $ok) { throw "PrintWindow failed for $($process.ProcessName)" }

    # Wrap the GDI bitmap in a .NET Bitmap (owns the handle now).
    $bmp = [System.Drawing.Bitmap]::FromHandle($hBmp)

    # Clone it so we own independent data.
    $rectClone = New-Object System.Drawing.Rectangle(0, 0, $w, $hgt)
    $clone = $bmp.Clone($rectClone, $bmp.PixelFormat)
    $bmp.Dispose()
} finally {
    [G]::DeleteObject($hBmp) | Out-Null
    if ($memDC -ne [IntPtr]::Zero) { [G]::DeleteDC($memDC) | Out-Null }
}
[G]::ReleaseDC($hWnd, $hDC) | Out-Null

# Ensure output directory exists.
$outDir = Split-Path $Out -Parent
if ($outDir -and (-not (Test-Path $outDir))) { New-Item -ItemType Directory -Force $outDir | Out-Null }

$clone.Save($Out, [System.Drawing.Imaging.ImageFormat]::PNG)
$clone.Dispose()
"[shot] saved $Out ($w x $hgt from PID $Pid)"

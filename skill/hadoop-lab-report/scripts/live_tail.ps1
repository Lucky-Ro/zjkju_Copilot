<#
live_tail.ps1 -- open a live-updating console that streams a log file in real time,
so the user can watch what the run is doing (interactive OR background/subagent).

Fixes vs a naive `Get-Content -Wait`:
  * prints the EXISTING content immediately (no "first lines missing"),
  * low-latency follow (~150ms) instead of Get-Content -Wait's ~1s poll,
  * resolves the path to ABSOLUTE (a new powershell's CWD may differ -> blank window),
  * UTF-8 so Chinese shows, and color-codes commands / headers / errors.

ASCII-only on purpose (Windows PowerShell 5.1 reads .ps1 as GBK without a BOM);
the log CONTENT is read as UTF-8 so Chinese is fine.

Usage (ssh_runner launches this automatically; you can also run it yourself):
  powershell -ExecutionPolicy Bypass -File scripts\live_tail.ps1 -Path <abs-or-rel path to run.log>
#>
param(
  [Parameter(Mandatory=$true)] [string]$Path
)

# Resolve to absolute so it works no matter what CWD this window starts in.
$abs = $Path
try { $abs = [System.IO.Path]::GetFullPath($Path) } catch { }

try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$Host.UI.RawUI.WindowTitle = "Hadoop Lab Report - LIVE"
Write-Host "==== LIVE VIEW (real time) ====" -ForegroundColor Cyan
Write-Host $abs -ForegroundColor DarkGray
Write-Host "------------------------------------------------------------"

# Wait for the file to appear (ssh_runner touches it before launching us, so this is brief).
$n = 0
while (-not (Test-Path $abs)) {
  Start-Sleep -Milliseconds 200
  $n++
  if ($n % 25 -eq 0) { Write-Host "(waiting for log file to appear...)" -ForegroundColor DarkYellow }
}

function Write-Line([string]$line) {
  if     ($line.StartsWith(">> ")) { Write-Host $line -ForegroundColor Cyan }
  elseif ($line.StartsWith("### ")) { Write-Host $line -ForegroundColor Yellow }
  elseif ($line -match '(?i)error|fail|exception|denied|refused|traceback|\bFAILED\b') { Write-Host $line -ForegroundColor Red }
  else   { Write-Host $line }
}

# Open with shared read/write so python can keep appending while we read.
$fs = [System.IO.File]::Open($abs, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
$sr = New-Object System.IO.StreamReader($fs, [System.Text.Encoding]::UTF8)
try {
  while ($true) {
    $line = $sr.ReadLine()
    if ($null -ne $line) { Write-Line $line }
    else { Start-Sleep -Milliseconds 150 }   # at EOF: wait briefly, then keep following
  }
} finally {
  $sr.Dispose(); $fs.Dispose()
}

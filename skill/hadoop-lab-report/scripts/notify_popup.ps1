<#
notify_popup.ps1 -- attention-grabbing popup for the "remote help" pause mode.

IMPORTANT (encoding): Windows PowerShell 5.1 reads .ps1 files as the system ANSI
code page (GBK/936 on zh-CN) unless they have a BOM. To stay robust, this script is
ASCII-only. Pass Chinese text via -MessageFile (a UTF-8 file), NOT inline on the
command line, to avoid mojibake. Never put passwords in the message.

Usage:
  # ASCII inline:
  powershell -ExecutionPolicy Bypass -File notify_popup.ps1 "stuck at 4.1 step3, fix NIC then reply 'continue'"
  # Chinese via UTF-8 file (recommended):
  #   write the message to runs/<eNN>/_popup.txt as UTF-8, then:
  powershell -ExecutionPolicy Bypass -File notify_popup.ps1 -MessageFile runs/e04/_popup.txt

Tip: launch it detached (Start-Process) so the modal MessageBox does not block your flow.
#>
param(
  [Parameter(Position=0)] [string]$Message = "",
  [string]$MessageFile = "",
  [string]$Title = "Hadoop Lab Report Copilot - need your help"
)

$ErrorActionPreference = "SilentlyContinue"

if ($MessageFile -ne "" -and (Test-Path $MessageFile)) {
  $Message = Get-Content -Path $MessageFile -Encoding UTF8 -Raw
}
if ($Message -eq "") { $Message = "Paused: please check the conversation and follow the instructions." }

# 1) BurntToast notification (non-blocking) if installed
if (Get-Module -ListAvailable -Name BurntToast) {
  try {
    Import-Module BurntToast -ErrorAction Stop
    New-BurntToastNotification -Text $Title, $Message
    Write-Output "NOTIFY_BURNTTOAST"
    return
  } catch { }
}

# 2) System.Windows.Forms.MessageBox (topmost modal); .NET ships with Win10
try {
  Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
  $form = New-Object System.Windows.Forms.Form
  $form.TopMost = $true
  [System.Windows.Forms.MessageBox]::Show(
    $form, $Message, $Title,
    [System.Windows.Forms.MessageBoxButtons]::OK,
    [System.Windows.Forms.MessageBoxIcon]::Warning) | Out-Null
  Write-Output "NOTIFY_MESSAGEBOX"
  return
} catch { }

# 3) msg.exe fallback (may be absent on some Home editions)
try {
  & msg.exe * /TIME:0 "$Title : $Message"
  Write-Output "NOTIFY_MSG"
  return
} catch { }

# 4) Last resort: beep + console print
[console]::beep(880,300)
Write-Output ("NOTIFY_FALLBACK_CONSOLE: " + $Title + " - " + $Message)

# BudsDesk installer for Windows:  irm https://raw.githubusercontent.com/Prateek1771/budsdesk/main/install.ps1 | iex
# Downloads the latest BudsDesk-Setup.exe and installs it for the current user (no admin).
$ErrorActionPreference = "Stop"
$setup = Join-Path $env:TEMP "BudsDesk-Setup.exe"
Write-Host "Downloading BudsDesk..."
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest "https://github.com/Prateek1771/budsdesk/releases/latest/download/BudsDesk-Setup.exe" -OutFile $setup -UseBasicParsing
Write-Host "Installing..."
Start-Process $setup -ArgumentList "/VERYSILENT", "/CURRENTUSER", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait
Remove-Item $setup -ErrorAction SilentlyContinue
$exe = Join-Path $env:LOCALAPPDATA "Programs\BudsDesk\BudsDesk.exe"
if (Test-Path $exe) { Write-Host "Installed. Starting BudsDesk (also in the Start menu)."; Start-Process $exe }
else { Write-Host "Install did not complete. Download it manually: https://github.com/Prateek1771/budsdesk/releases/latest" }

# Build dist\Jarvis-Setup-<version>.exe on Windows (needs Inno Setup 6: winget install JRSoftware.InnoSetup).
#   powershell -ExecutionPolicy Bypass -File platform\win\build.ps1
$ErrorActionPreference = "Stop"
$Root = Resolve-Path "$PSScriptRoot\..\.."
$Ver = (Get-Content "$Root\VERSION").Trim()
$PbsTag = if ($env:PBS_TAG) { $env:PBS_TAG } else { "20241016" }
$PyVer = if ($env:PY_VER) { $env:PY_VER } else { "3.12.7" }
$Out = "$Root\dist"; $Src = "$Out\win"
if (Test-Path $Src) { Remove-Item -Recurse -Force $Src }
New-Item -ItemType Directory -Force "$Src", "$Out\cache" | Out-Null

foreach ($d in "jarvis", "hud", "app") {
  robocopy "$Root\$d" "$Src\$d" /E /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS | Out-Null
}
Copy-Item "$Root\requirements.txt", "$Root\VERSION", "$Root\LICENSE", "$Root\NOTICE.md" "$Src\"

$Pbs = "cpython-$PyVer+$PbsTag-x86_64-pc-windows-msvc-install_only.tar.gz"
if (-not (Test-Path "$Out\cache\$Pbs")) {
  Invoke-WebRequest "https://github.com/astral-sh/python-build-standalone/releases/download/$PbsTag/$Pbs" -OutFile "$Out\cache\$Pbs"
}
tar -xzf "$Out\cache\$Pbs" -C "$Src"          # -> dist\win\python

$Iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) { throw "Inno Setup 6 not found" }
& $Iscc "/DVERSION=$Ver" "/DSRC=$Src" "$PSScriptRoot\jarvis.iss"
Write-Host "built $Out\Jarvis-Setup-$Ver.exe"

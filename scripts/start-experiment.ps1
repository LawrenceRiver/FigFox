param([string[]]$Images, [string]$InputDir = '', [string]$Out = '', [double]$TargetUsd = 1)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'windows-env.ps1')
$launchArgs = @('--target-usd', "$TargetUsd")
if ($Images) { $launchArgs += $Images }
if ($InputDir) { $launchArgs += @('--input-dir', $InputDir) }
if ($Out) { $launchArgs += @('--out', $Out) }
& $FigFoxPython (Join-Path $PSScriptRoot 'background-experiment.py') @launchArgs
exit $LASTEXITCODE

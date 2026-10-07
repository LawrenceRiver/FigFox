param([Parameter(Mandatory = $true)][string]$Image,
      [Parameter(Mandatory = $true)][string]$Id,
      [Parameter(Mandatory = $true)][string]$Out,
      [string]$Authorization = '', [switch]$Background)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'windows-env.ps1')
# Resolve relative inputs before changing directory.
$Image = (Resolve-Path -LiteralPath $Image).Path
$Out = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Out)
if (Test-Path -LiteralPath $Out) { throw "Output already exists: $Out" }
if (-not $Authorization) { $Authorization = [guid]::NewGuid().ToString() }
if ($Background) {
    & $FigFoxPython (Join-Path $PSScriptRoot 'background-experiment.py') $Image --chain --id $Id --out $Out --authorization $Authorization
    exit $LASTEXITCODE
}
& $FigFoxPython (Join-Path $PSScriptRoot 'check-runtime.py') --credentials --sandbox
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Push-Location $FigFoxRoot
try {
    & $FigFoxPython -m figfox_plus chain --image $Image --id $Id --out $Out --rerun-authorization $Authorization
    $FigFoxExitCode = $LASTEXITCODE
} finally { Pop-Location }
exit $FigFoxExitCode

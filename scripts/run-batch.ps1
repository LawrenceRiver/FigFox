[CmdletBinding(DefaultParameterSetName = 'Dataset')]
param([Parameter(Mandatory = $true, ParameterSetName = 'Folder')][string]$InputDir,
      [Parameter(ParameterSetName = 'Folder')][string]$Out = '',
      [Parameter(Mandatory = $true, ParameterSetName = 'Dataset')][string]$Dataset,
      [Parameter(ParameterSetName = 'Dataset')][string[]]$Samples,
      [Parameter(ParameterSetName = 'Dataset')][string]$RunId = '', [switch]$Background)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'windows-env.ps1')
if ($PSCmdlet.ParameterSetName -eq 'Dataset') {
    if ($Background) {
        $launchArgs = @('--dataset', $Dataset)
        if ($RunId) { $launchArgs += @('--run-id', $RunId) }
        if ($Samples) { $launchArgs += @('--samples') + $Samples }
        & $FigFoxPython (Join-Path $PSScriptRoot 'background-experiment.py') @launchArgs
        exit $LASTEXITCODE
    }
    $benchmarkArgs = @('run-figfox', '--dataset', $Dataset)
    if ($RunId) { $benchmarkArgs += @('--run-id', $RunId) }
    if ($Samples) { $benchmarkArgs += @('--samples') + $Samples }
    & $FigFoxPython (Join-Path $PSScriptRoot 'benchmark.py') @benchmarkArgs
    exit $LASTEXITCODE
}
if (-not $Out) { $Out = Join-Path $FigFoxRoot ('runs/experiments/' + (Get-Date -Format 'yyyyMMdd-HHmmss')) }
if ($Background) {
    & $FigFoxPython (Join-Path $PSScriptRoot 'background-experiment.py') --input-dir $InputDir --out $Out
    exit $LASTEXITCODE
}
& $FigFoxPython (Join-Path $PSScriptRoot 'batch-experiment.py') --input-dir $InputDir --out $Out
exit $LASTEXITCODE

param([Parameter(Mandatory = $true)][string]$PayloadFile,
      [Parameter(Mandatory = $true)][string]$ReceiptFile)
$ErrorActionPreference = 'Stop'
# An interactive-user task starts outside a packaged host's virtualized AppData
# and registry. It runs once without elevation and is removed after the receipt.
$powershell = Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0/powershell.exe'
$helper = Join-Path $PSScriptRoot 'notify-windows.ps1'
$arguments = '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File "' + $helper + '" -PayloadFile "' + $PayloadFile + '" -ReceiptFile "' + $ReceiptFile + '"'
$service = New-Object -ComObject Schedule.Service
$service.Connect()
$folder = $service.GetFolder('\')
$definition = $service.NewTask(0)
$definition.Principal.UserId = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$definition.Principal.LogonType = 3
$definition.Principal.RunLevel = 0
$definition.Settings.AllowDemandStart = $true
$definition.Settings.DisallowStartIfOnBatteries = $false
$definition.Settings.StopIfGoingOnBatteries = $false
$definition.Settings.ExecutionTimeLimit = 'PT2M'
$action = $definition.Actions.Create(0)
$action.Path = $powershell
$action.Arguments = $arguments
$action.WorkingDirectory = $PSScriptRoot
$name = 'FigFox-926-Notify-' + [guid]::NewGuid().ToString('N')
$task = $folder.RegisterTaskDefinition($name, $definition, 2, $definition.Principal.UserId, $null, 3)
try {
    $task.Run($null) | Out-Null
    $deadline = [DateTime]::UtcNow.AddSeconds(25)
    while (-not (Test-Path -LiteralPath $ReceiptFile) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 250 }
} finally { $folder.DeleteTask($name, 0) }

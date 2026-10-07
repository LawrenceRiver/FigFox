param([Parameter(Mandatory = $true)][string]$PayloadFile, [string]$ReceiptFile = '')
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$payload = Get-Content -LiteralPath $PayloadFile -Raw -Encoding UTF8 | ConvertFrom-Json
function Show-FigFoxToast {
$protocolPath = 'HKCU:\Software\Classes\' + $payload.protocol
if (Test-Path -LiteralPath $protocolPath) {
    $owner = (Get-ItemProperty -LiteralPath $protocolPath -ErrorAction Stop).FigFoxWorkspace
    if ($owner -and $owner -ne $payload.workspace) { throw 'Notification protocol belongs to another workspace.' }
}
New-Item -Path $protocolPath -Force | Out-Null
New-ItemProperty -LiteralPath $protocolPath -Name '(default)' -Value 'URL:FigFox experiment results' -Force | Out-Null
New-ItemProperty -LiteralPath $protocolPath -Name 'URL Protocol' -Value '' -Force | Out-Null
New-ItemProperty -LiteralPath $protocolPath -Name 'FigFoxWorkspace' -Value $payload.workspace -Force | Out-Null
New-Item -Path ($protocolPath + '\shell\open\command') -Force | Out-Null
Set-Item -LiteralPath ($protocolPath + '\shell\open\command') -Value $payload.protocol_command
$appPath = 'HKCU:\Software\Classes\AppUserModelId\' + $payload.app_id
New-Item -Path $appPath -Force | Out-Null
New-ItemProperty -LiteralPath $appPath -Name 'DisplayName' -Value 'FigFox' -Force | Out-Null
New-ItemProperty -LiteralPath $appPath -Name 'CustomActivator' -Value '{B1AD1F9F-163A-43C5-A421-0A53ECB72926}' -Force | Out-Null
Add-Type -Path (Join-Path $PSScriptRoot '../runtime/toast-shortcut.cs')
$shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'FigFox Experiments 926.lnk'
[FigFoxToastShortcut]::Create($shortcut, $payload.executable, $payload.shortcut_arguments, $payload.workspace, $payload.app_id)
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.UI.Notifications.ToastNotifier, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.UI.Notifications.NotificationSetting, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$document = New-Object Windows.Data.Xml.Dom.XmlDocument
$document.LoadXml($payload.xml)
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($payload.app_id)
try { $setting = $notifier.GetType().GetProperty('Setting').GetValue($notifier, $null).ToString() }
catch { $setting = 'NotRegisteredYet' }
if ($setting -ne 'Enabled' -and $setting -ne 'NotRegisteredYet') {
    return @{status = 'disabled_by_windows'; setting = $setting}
}
$toast = [Windows.UI.Notifications.ToastNotification]::new($document)
$toast.ExpirationTime = [DateTimeOffset]::Now.AddDays(2)
$notifier.Show($toast)
if ($setting -eq 'NotRegisteredYet') {
    try { $setting = $notifier.GetType().GetProperty('Setting').GetValue($notifier, $null).ToString() }
    catch { $setting = 'Unknown' }
}
return @{status = 'submitted'; setting = $setting; shortcut = $shortcut}
}
try { $result = Show-FigFoxToast }
catch { $result = @{status = 'failed'; diagnostic = $_.Exception.Message; line = $_.InvocationInfo.ScriptLineNumber} }
$json = $result | ConvertTo-Json -Compress
if ($ReceiptFile) { [IO.File]::WriteAllText($ReceiptFile, $json, [Text.UTF8Encoding]::new($false)) }
else { $json }

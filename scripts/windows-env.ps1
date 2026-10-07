# Shared Windows setup. No POSIX shim and no machine-specific browser path.
$FigFoxRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$env:PYTHONPATH = Join-Path $FigFoxRoot 'src'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$FigFoxPython = Join-Path $FigFoxRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $FigFoxPython)) { $FigFoxPython = 'python' }
# Preserve explicitly configured environment values; .env.local precedes .env.
foreach ($name in @('.env.local', '.env')) {
    $file = Join-Path $FigFoxRoot $name
    if (-not (Test-Path -LiteralPath $file)) { continue }
    foreach ($line in Get-Content -LiteralPath $file -Encoding UTF8) {
        $entry = $line.Trim() -replace '^export\s+', ''
        if (-not $entry -or $entry.StartsWith('#') -or -not $entry.Contains('=')) { continue }
        $key, $value = $entry.Split('=', 2)
        $key = $key.Trim()
        if (-not [Environment]::GetEnvironmentVariable($key)) {
            [Environment]::SetEnvironmentVariable($key, $value.Trim().Trim('"').Trim("'"), 'Process')
        }
    }
}

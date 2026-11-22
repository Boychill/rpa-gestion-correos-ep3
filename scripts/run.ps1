param([Parameter(ValueFromRemainingArguments=$true)][string[]]$BotArgs)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $PythonExe)) { throw 'Ejecute scripts\setup.ps1 primero.' }
if (-not $BotArgs) { $BotArgs = @('run') }
& $PythonExe (Join-Path $ProjectRoot 'main.py') @BotArgs
exit $LASTEXITCODE

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
python -m venv (Join-Path $ProjectRoot '.venv')
if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno Python.' }
$PythonExe = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
& $PythonExe -m pip install -r (Join-Path $ProjectRoot 'requirements-lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Falló la instalación.' }
& $PythonExe (Join-Path $ProjectRoot 'main.py') init
exit $LASTEXITCODE

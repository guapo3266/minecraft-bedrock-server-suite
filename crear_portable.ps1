param()
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$portablePython = Join-Path $PSScriptRoot '.venv-portable\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $portablePython)) {
    python -m venv .venv-portable
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno de empaquetado.' }
}
& $portablePython -m pip install -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias de empaquetado.' }
& $portablePython tools/build_portable.py
if ($LASTEXITCODE -ne 0) { throw 'Fallo la construccion del portable.' }

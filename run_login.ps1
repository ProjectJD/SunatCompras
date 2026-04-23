Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Error "No existe el entorno virtual. Sigue primero los pasos del README."
    exit 1
}

& ".\.venv\Scripts\python.exe" -m src.login @args

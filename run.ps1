$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv")) {
    py -m venv .venv
}

& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
$markOsUvicornArgs = @("app.main:app", "--reload")
if (Test-Path ".env") {
    $markOsUvicornArgs = @("--env-file", ".env") + $markOsUvicornArgs
}
python -m uvicorn @markOsUvicornArgs

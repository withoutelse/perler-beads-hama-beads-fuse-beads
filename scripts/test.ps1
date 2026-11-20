$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$env:PYTHONPATH = "apps/api"
python -m unittest discover -s apps/api/tests -v
python -m compileall apps/api/app

# Build and analyse families one after another (a slow family must not starve the plastic runs of memory).
#   powershell -File dataset\run_queue.ps1 fin_thermal:80 square_hole_thermal:60
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Families)
$studio = Split-Path $PSScriptRoot -Parent
Set-Location $studio
$env:PYTHONPATH = "$studio\backend"
$env:NOVASTUDIO_SOLVER_SLOTS = "4"
$env:PYTHONIOENCODING = "utf-8"
foreach ($item in $Families) {
    $name, $n = $item -split ":"
    $out = "dataset\out\$name"
    New-Item -ItemType Directory -Force $out | Out-Null
    & .\.venv\Scripts\python.exe dataset\build.py --family $name --n $n --workers 1 2>&1 |
        Where-Object { $_ -match '^\[|done,' } | ForEach-Object { $_.ToString() } | Add-Content -Encoding utf8 "$out\build.log"
    & .\.venv\Scripts\python.exe dataset\analyze.py --family $name 2>&1 | ForEach-Object { $_.ToString() } | Set-Content -Encoding utf8 "$out\analyze.log"
    "$name done $(Get-Date -Format 'MM-dd HH:mm')"
}

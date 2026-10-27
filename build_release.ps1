# Build the portable Windows release: release/NovaSolverStudio-<version>-win64.zip (+ .sha256)
# Usage:  powershell -ExecutionPolicy Bypass -File build_release.ps1 [-SkipFrontend]
param([switch]$SkipFrontend)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$version = (& $py -c "import sys; sys.path.insert(0, r'$root\backend'); import novastudio; print(novastudio.__version__)").Trim()
$name = "NovaSolverStudio-$version-win64"
Write-Host "Building $name"

if (-not $SkipFrontend) {
    Push-Location (Join-Path $root "frontend"); npm run build; if ($LASTEXITCODE) { throw "frontend build failed" }; Pop-Location
}

$work = Join-Path $root "build"
Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
& $py -m PyInstaller --noconfirm --clean --onedir --console --name NovaSolverStudio `
    --distpath (Join-Path $work "dist") --workpath (Join-Path $work "work") --specpath $work `
    --paths (Join-Path $root "backend") `
    --collect-all gmsh --collect-all pymeshlab --collect-submodules novastudio --collect-submodules uvicorn `
    --collect-submodules mcp.server --collect-submodules mcp.shared --collect-submodules mcp.types --collect-submodules mcp_types --exclude-module mcp.cli `
    --collect-submodules pyamg --hidden-import scipy.sparse.linalg --hidden-import matplotlib.backends.backend_agg `
    --add-data "$root\backend\novastudio\i18n;novastudio\i18n" `
    --add-data "$root\frontend\dist;frontend\dist" `
    --add-data "$root\samples;samples" `
    (Join-Path $root "backend\launcher.py")
if ($LASTEXITCODE) { throw "PyInstaller failed" }

$app = Join-Path $work "dist\NovaSolverStudio"
# bundled solvers (redistributable): CalculiX (GPL-2.0, source link in THIRD_PARTY_NOTICES) and the MS-MPI runtime (MIT)
$ccx = Get-ChildItem (Join-Path $root "solvers\calculix") -Recurse -Filter ccx_static.exe | Select-Object -First 1
if ($ccx) { New-Item -ItemType Directory -Force "$app\solvers\calculix" | Out-Null; Copy-Item $ccx.FullName "$app\solvers\calculix\" }
$mpi = Join-Path $env:LOCALAPPDATA "NovaSolverStudio\solvers\msmpi"
if (Test-Path "$mpi\msmpi.dll") { New-Item -ItemType Directory -Force "$app\solvers\msmpi" | Out-Null; Copy-Item "$mpi\*" "$app\solvers\msmpi\" }
& (Join-Path $root "prune_bundle.ps1") $app
Copy-Item (Join-Path $root "LICENSE"), (Join-Path $root "THIRD_PARTY_NOTICES.md"), (Join-Path $root "README.md") $app
@"
NovaSolver Studio $version

1. Double-click NovaSolverStudio.exe. Your browser opens the app (http://127.0.0.1:8765).
2. Built-in preview solvers and CalculiX work right away.
3. For flow analyses, install OpenFOAM (ESI Windows build) to %LOCALAPPDATA%\NovaSolverStudio\solvers\openfoam
   - see https://novasolver.jp/studio/ for the guide.
Cases are saved in Documents\NovaSolverStudio\workspace.

ダブルクリックで起動するとブラウザに画面が開きます。流れの解析には OpenFOAM の導入が必要です（案内: https://novasolver.jp/studio/）。
"@ | Set-Content -Encoding UTF8 (Join-Path $app "START_HERE.txt")

$rel = Join-Path $root "release"; New-Item -ItemType Directory -Force $rel | Out-Null
$zip = Join-Path $rel "$name.zip"; Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path $app -DestinationPath $zip
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
"$hash  $name.zip" | Set-Content -Encoding ASCII "$zip.sha256"
Write-Host ("{0}  {1:N1} MB  sha256 {2}" -f $zip, ((Get-Item $zip).Length / 1MB), $hash)

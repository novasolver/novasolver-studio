# Build the portable Windows release: release/NovaSolverStudio-<version>-win64.zip (+ .sha256)
# Usage:  powershell -ExecutionPolicy Bypass -File build_release.ps1 [-SkipFrontend] [-Stage all|app|package]
#   app      build the program folder only (build\dist\NovaSolverStudio): CI signs the exe in between
#   package  zip + installer from that folder (after signing)
param([switch]$SkipFrontend, [ValidateSet("all", "app", "package")][string]$Stage = "all")
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$version = (& $py -c "import sys; sys.path.insert(0, r'$root\backend'); import novastudio; print(novastudio.__version__)").Trim()
$name = "NovaSolverStudio-$version-win64"
Write-Host "Building $name"

$work = Join-Path $root "build"
$app = Join-Path $work "dist\NovaSolverStudio"
$rel = Join-Path $root "release"
if ($Stage -ne "package") {
if (-not $SkipFrontend) {
    Push-Location (Join-Path $root "frontend"); npm run build; if ($LASTEXITCODE) { throw "frontend build failed" }; Pop-Location
}

Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
# --console stays: "NovaSolverStudio.exe mcp" talks to Claude and other MCP clients over stdio. In app mode the exe
# hides that console itself and shows the UI in its own window (novastudio/desktop.py).
& $py -m PyInstaller --noconfirm --clean --onedir --console --name NovaSolverStudio `
    --icon (Join-Path $root "assets\NovaSolverStudio.ico") `
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

# bundled solvers (redistributable): CalculiX (GPL-2.0, source link in THIRD_PARTY_NOTICES) and the MS-MPI runtime (MIT)
$ccx = Get-ChildItem (Join-Path $root "solvers\calculix") -Recurse -Filter ccx_static.exe | Select-Object -First 1
if ($ccx) { New-Item -ItemType Directory -Force "$app\solvers\calculix" | Out-Null; Copy-Item $ccx.FullName "$app\solvers\calculix\" }
$mpi = Join-Path $env:LOCALAPPDATA "NovaSolverStudio\solvers\msmpi"
if (Test-Path "$mpi\msmpi.dll") { New-Item -ItemType Directory -Force "$app\solvers\msmpi" | Out-Null; Copy-Item "$mpi\*" "$app\solvers\msmpi\" }
& (Join-Path $root "prune_bundle.ps1") $app
Copy-Item (Join-Path $root "LICENSE"), (Join-Path $root "THIRD_PARTY_NOTICES.md"), (Join-Path $root "README.md") $app
@"
NovaSolver Studio $version

1. Double-click NovaSolverStudio.exe. The app opens in its own window; closing the window ends the program.
   (The installer version, NovaSolverStudio-$version-win64-setup.exe, also adds a Start menu entry and opens
   .nscase files by double-click.)
2. Built-in preview solvers and CalculiX work right away.
3. For flow analyses, install OpenFOAM (ESI Windows build) to %LOCALAPPDATA%\NovaSolverStudio\solvers\openfoam
   - see https://novasolver.jp/studio/ for the guide.
Cases are saved in Documents\NovaSolverStudio\workspace.

ダブルクリックで起動すると専用のウィンドウが開きます（閉じると終了）。流れの解析には OpenFOAM の導入が必要です（案内: https://novasolver.jp/studio/）。
"@ | Set-Content -Encoding UTF8 (Join-Path $app "START_HERE.txt")
}
if ($Stage -eq "app") { Write-Host "App folder ready: $app"; return }
if (-not (Test-Path (Join-Path $app "NovaSolverStudio.exe"))) { throw "no app folder: run with -Stage app first" }

New-Item -ItemType Directory -Force $rel | Out-Null
$zip = Join-Path $rel "$name.zip"; Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path $app -DestinationPath $zip
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
"$hash  $name.zip" | Set-Content -Encoding ASCII "$zip.sha256"
Write-Host ("{0}  {1:N1} MB  sha256 {2}" -f $zip, ((Get-Item $zip).Length / 1MB), $hash)

# Installer (Start menu, desktop icon, .nscase association, uninstall). Inno Setup is preinstalled on GitHub's
# windows runners; locally it is skipped when ISCC.exe is not found.
$iscc = @((Get-Command iscc.exe -ErrorAction SilentlyContinue).Source, "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") |
        Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($iscc) {
    & $iscc /Q "/DAppVersion=$version" "/DAppDir=$app" "/DOutDir=$rel" (Join-Path $root "installer\NovaSolverStudio.iss")
    if ($LASTEXITCODE) { throw "installer build failed" }
    $setup = Join-Path $rel "$name-setup.exe"
    $h = (Get-FileHash $setup -Algorithm SHA256).Hash.ToLower()
    "$h  $name-setup.exe" | Set-Content -Encoding ASCII "$setup.sha256"
    Write-Host ("{0}  {1:N1} MB  sha256 {2}" -f $setup, ((Get-Item $setup).Length / 1MB), $h)
} else {
    Write-Host "Inno Setup not found: installer skipped (zip only)"
}

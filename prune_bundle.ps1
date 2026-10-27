# Remove files the packaged app never loads at run time (called by build_release.ps1; about 47 MB off the zip).
# Usage:  powershell -ExecutionPolicy Bypass -File prune_bundle.ps1 <dist\NovaSolverStudio>
param([Parameter(Mandatory)][string]$App)
$ErrorActionPreference = "Stop"
$internal = Join-Path $App "_internal"
if (-not (Test-Path (Join-Path $internal "pymeshlab"))) { throw "not a NovaSolver Studio bundle: $App" }
$before = (Get-ChildItem $App -Recurse -File | Measure-Object Length -Sum).Sum

# fonts: every @font-face lists woff2 first, which the browser always takes; the .woff copies are never fetched
Get-ChildItem (Join-Path $internal "frontend\dist\assets") -File | Where-Object Extension -eq ".woff" | Remove-Item
$pml = Join-Path $internal "pymeshlab"
# PyMeshLab: its own test meshes, link-time import libraries, Qt's software OpenGL fallback (only used for
# rendering, which the app never asks for) and Embree with the ray-casting plugin that needs it
Remove-Item -Recurse -Force (Join-Path $pml "tests") -ErrorAction SilentlyContinue
Get-ChildItem $pml -Recurse -File | Where-Object Extension -eq ".lib" | Remove-Item
foreach ($f in "opengl32sw.dll", "embree4.dll", "lib\plugins\filter_embree.dll") {
    Remove-Item -Force (Join-Path $pml $f) -ErrorAction SilentlyContinue
}

$after = (Get-ChildItem $App -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ("pruned {0:N1} MB (unpacked) from {1}" -f (($before - $after) / 1MB), $App)

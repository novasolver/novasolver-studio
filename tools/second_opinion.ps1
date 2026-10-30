# Second opinion: Codex reviews NovaSolver Studio read-only and writes studio/reviews/<date>_<label>.codex.md
# Usage:  powershell -ExecutionPolicy Bypass -File tools\second_opinion.ps1 -Since v0.2.1
#         powershell -ExecutionPolicy Bypass -File tools\second_opinion.ps1 -Full
#         add -DeepSeekFirst to run tools\ds_review.py (deepseek-reasoner, cheap) first; Codex then verifies its findings
#         instead of hunting from scratch, and looks only for what it missed.
param([string]$Since, [switch]$Full, [string]$Model = 'gpt-6.1-sol', [string]$Effort = 'high', [switch]$DeepSeekFirst)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $Full -and -not $Since) { throw 'give -Since <tag> or -Full' }
$codex = Get-ChildItem "$env:LOCALAPPDATA\OpenAI\Codex\bin" -Recurse -Filter codex.exe |
    Where-Object { $_.DirectoryName -ne "$env:LOCALAPPDATA\OpenAI\Codex\bin" } |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $codex) { throw 'codex.exe not found under %LOCALAPPDATA%\OpenAI\Codex\bin' }
$label = if ($Full) { 'full' } else { "since-$Since" }
$date = Get-Date -Format 'yyyy-MM-dd'
$out = Join-Path $root "reviews\${date}_$label.codex.md"
New-Item -ItemType Directory -Force (Join-Path $root 'reviews') | Out-Null
$scope = if ($Full) { 'the whole code base under backend/ and frontend/src/ (skip node_modules, build, .venv, marketing).' }
         else { "the changes since $Since (run: git diff $Since..HEAD -- backend frontend/src) and the code they call." }
$hint = ''
if ($DeepSeekFirst -and $Since) {
    $env:DEEPSEEK_MODEL = 'deepseek-reasoner'
    python (Join-Path $PSScriptRoot 'ds_review.py') diff $Since   # the printed path is mangled by the console code page
    $ds = Join-Path $root ("reviews\{0}_since-{1}.deepseek-reasoner.md" -f (Get-Date -Format 'yyyy-MM-dd'), ($Since -replace '\.\.', '_to_'))
    if (Test-Path $ds) {
        $hint = "A cheaper model already reviewed the same changes: $ds. Its findings are unverified (in calibration about a third were wrong). First mark each one CONFIRMED or REJECTED with the reason, then spend the rest of your effort on what it missed: security of downloads and updates, data loss, wrong physics."
    }
}
$prompt = @"
You are giving a second opinion on NovaSolver Studio, a desktop CAE app (Python FastAPI + MCP backend, built-in FEM,
CalculiX and OpenFOAM; React + three.js frontend). Read .claude/skills/second-opinion/SKILL.md for what to look for and
the required format. Review $scope
You are read-only: do not modify any file. Print the report as Markdown: a summary table (severity, file:line, one line),
then one section per finding with: what goes wrong (concrete input -> wrong result), why, and a suggested fix.
Order by severity. If you find nothing in a category, say so in one line. No style comments.
$hint
"@
Push-Location $root
# codex prints progress on stderr and would wait for stdin: give it an empty stdin and do not treat stderr as an error
$ErrorActionPreference = 'Continue'
try {
    '' | & $codex.FullName exec --model $Model -c "model_reasoning_effort=`"$Effort`"" --sandbox read-only --skip-git-repo-check `
        -C $root --output-last-message $out $prompt *> (Join-Path $root "reviews\${date}_$label.log")
} finally { Pop-Location; $ErrorActionPreference = 'Stop' }
if (-not (Test-Path $out)) { throw "no report written; see reviews\${date}_$label.log" }
Write-Host "report: $out"

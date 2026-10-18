param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
$ErrorActionPreference = 'Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
    $bundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $bundledPython) { & $bundledPython -m repair_agent @Arguments }
    elseif (Get-Command py -ErrorAction SilentlyContinue) { & py -3 -m repair_agent @Arguments }
    else { & python -m repair_agent @Arguments }
    $code = $LASTEXITCODE
} finally { Pop-Location }
exit $code

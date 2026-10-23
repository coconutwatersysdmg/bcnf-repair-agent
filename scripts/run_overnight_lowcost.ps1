# Overnight low-cost matrix: Qwen (paid) + GLM-4.7-flash (listed free).
# Resumable: re-running the same --out continues unfinished jobs.
# Detach-friendly: can outlive the Cursor session.

$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

$LogDir = Join-Path $Root 'runs\overnight_lowcost_20261022'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir 'overnight.log'

function Log([string]$msg) {
    $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Add-Content -LiteralPath $Log -Value $line -Encoding UTF8
    Write-Output $line
}

function Ensure-Key([string]$name) {
    $cur = [Environment]::GetEnvironmentVariable($name, 'Process')
    if ([string]::IsNullOrWhiteSpace($cur)) {
        $u = [Environment]::GetEnvironmentVariable($name, 'User')
        if (-not [string]::IsNullOrWhiteSpace($u)) {
            Set-Item -Path "Env:$name" -Value $u
        }
    }
    $ok = -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($name, 'Process'))
    Log ("ENV {0}={1}" -f $name, $ok)
    return $ok
}

function Invoke-Py([string[]]$PyArgs) {
    Log ("CMD python -m repair_agent " + ($PyArgs -join ' '))
    & python -m repair_agent @PyArgs
    $code = $LASTEXITCODE
    Log ("EXIT $code")
    return $code
}

Log '=== overnight pipeline start ==='
Log ("Root=$Root")

$hasQwen = Ensure-Key 'DASHSCOPE_API_KEY'
$hasGlm = Ensure-Key 'ZAI_API_KEY'
if (-not $hasQwen) { Log 'FATAL: DASHSCOPE_API_KEY missing'; exit 2 }
if (-not $hasGlm) { Log 'WARN: ZAI_API_KEY missing; GLM stage will fail' }

$Data = 'data\theory_main_synth_20261022'
$Public = Join-Path $Data 'public.jsonl'
$Truth = Join-Path $Data 'private_truth.jsonl'
$Arms = 'D0,B0,B1,B2,B3,B3_truncate,B3_random'
$QwenRun = 'runs\qwen_theory_main_20261022'
$GlmRun = 'runs\glm_theory_main_20261022'

if (-not (Test-Path -LiteralPath $Public)) {
    Log 'Generating synthetic main dataset count=300 ...'
    $c = Invoke-Py @(
        'generate', '--out', $Data, '--count', '300', '--entities', '8',
        '--seed', '2026102203', '--split', 'test'
    )
    if ($c -ne 0) { Log 'FATAL: generate failed'; exit $c }
} else {
    Log "Dataset exists: $Data"
}

# --- Qwen paid main matrix ---
if ($hasQwen) {
    Log 'STAGE Qwen LIVE main matrix (resumable)'
    $c = Invoke-Py @(
        'run', '--data', $Public, '--out', $QwenRun,
        '--config', 'configs\qwen-theory-main.json',
        '--mode', 'live', '--live',
        '--arms', $Arms, '--repeats', '3'
    )
    Log "Qwen run finished exit=$c"
    if (Test-Path -LiteralPath (Join-Path $QwenRun 'results.jsonl')) {
        Invoke-Py @('status', '--run', $QwenRun) | Out-Null
        Invoke-Py @('evaluate', '--run', $QwenRun, '--truth', $Truth) | Out-Null
        Invoke-Py @('analyze', '--run', $QwenRun) | Out-Null
        Invoke-Py @('replay', '--run', $QwenRun) | Out-Null
        Log 'Qwen evaluate/analyze/replay done (or attempted)'
    }
}

# --- GLM free main matrix ---
if ($hasGlm) {
    Log 'STAGE GLM LIVE main matrix (resumable; free tier may 429)'
    $c = Invoke-Py @(
        'run', '--data', $Public, '--out', $GlmRun,
        '--config', 'configs\glm-theory-main.json',
        '--mode', 'live', '--live',
        '--arms', $Arms, '--repeats', '3'
    )
    Log "GLM run finished exit=$c"
    if (Test-Path -LiteralPath (Join-Path $GlmRun 'results.jsonl')) {
        Invoke-Py @('status', '--run', $GlmRun) | Out-Null
        Invoke-Py @('evaluate', '--run', $GlmRun, '--truth', $Truth) | Out-Null
        Invoke-Py @('analyze', '--run', $GlmRun) | Out-Null
        Invoke-Py @('replay', '--run', $GlmRun) | Out-Null
        Log 'GLM evaluate/analyze/replay done (or attempted)'
    }
}

Log '=== overnight pipeline end ==='
# Write a short morning summary
$Summary = Join-Path $LogDir 'MORNING_STATUS.txt'
$lines = @()
$lines += "Finished at $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
foreach ($run in @($QwenRun, $GlmRun)) {
    $sum = Join-Path $run 'run_summary.json'
    if (Test-Path -LiteralPath $sum) {
        $lines += "---- $run ----"
        $lines += (Get-Content -LiteralPath $sum -Raw)
    } else {
        $lines += "---- $run ---- MISSING run_summary.json"
    }
}
$lines | Set-Content -LiteralPath $Summary -Encoding UTF8
Log "Wrote $Summary"
exit 0

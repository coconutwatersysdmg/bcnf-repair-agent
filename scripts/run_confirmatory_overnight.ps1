$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

$LogDir = Join-Path $Root 'runs\confirmatory_overnight_20261023'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir 'overnight.log'
$Arms = 'D0,D1,B0,B1,B2,B3_192,B3_truncate_192,B3_random_192,B3_384,B3_truncate_384,B3_random_384'

function Log([string]$Message) {
    $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -LiteralPath $Log -Value $line -Encoding UTF8
}

function Ensure-Key([string]$Name) {
    if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($Name,'Process'))) {
        $value = [Environment]::GetEnvironmentVariable($Name,'User')
        if (-not [string]::IsNullOrWhiteSpace($value)) { Set-Item -Path "Env:$Name" -Value $value }
    }
    return -not [string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($Name,'Process'))
}

function Run-Python([string[]]$Arguments) {
    Log ('CMD python ' + ($Arguments -join ' '))
    & python @Arguments *>> $Log
    $code=$LASTEXITCODE
    Log "EXIT $code"
    return $code
}

Log '=== confirmatory overnight start ==='
if (-not (Ensure-Key 'DASHSCOPE_API_KEY')) { Log 'FATAL DASHSCOPE_API_KEY missing'; exit 2 }

# Wait for the preserved exploratory Qwen child, if it is still alive.
while (Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'qwen_theory_main_20261022' }) {
    Log 'Waiting for exploratory Qwen run to finish before new paid calls.'
    Start-Sleep -Seconds 30
}

$PilotData='data\confirm_paired_pilot_20261023'
$PilotRun='runs\qwen_confirm_pilot_20261023'
$PilotTruth=Join-Path $PilotData 'private_truth.jsonl'
if (-not (Test-Path -LiteralPath $PilotData)) {
    $code=Run-Python @('-m','repair_agent','generate-paired','--out',$PilotData,'--pairs','15','--entities','8','--seed','2026102301','--split','test')
    if($code -ne 0){exit $code}
}
$code=Run-Python @('-m','repair_agent','run','--data',(Join-Path $PilotData 'public.jsonl'),'--out',$PilotRun,
    '--config','configs\qwen-confirm-pilot.json','--mode','live','--live','--arms',$Arms,'--repeats','1')
if($code -ne 0){exit $code}
Run-Python @('-m','repair_agent','evaluate','--run',$PilotRun,'--truth',$PilotTruth) | Out-Null
Run-Python @('-m','repair_agent','analyze','--run',$PilotRun) | Out-Null
Run-Python @('-m','repair_agent','replay','--run',$PilotRun) | Out-Null
$PilotReport='reports\progress\qwen_confirm_pilot_gate_20261023.json'
$code=Run-Python @('scripts\audit_confirmatory_run.py','--run',$PilotRun,'--out',$PilotReport,'--min-policy-differences','3')
if($code -ne 0){Log 'Pilot gate failed; full matrix will not start.';exit $code}

& git add configs/qwen-confirm-pilot.json configs/qwen-confirm-main.json $PilotReport
& git commit -m 'exp: pass Qwen paired confirmation pilot gate' *>> $Log

$MainData='data\confirm_paired_synth_20261023'
$MainRun='runs\qwen_confirm_paired_20261023'
$MainTruth=Join-Path $MainData 'private_truth.jsonl'
if (-not (Test-Path -LiteralPath $MainData)) {
    $code=Run-Python @('-m','repair_agent','generate-paired','--out',$MainData,'--pairs','90','--entities','8','--seed','2026102302','--split','test')
    if($code -ne 0){exit $code}
}
$code=Run-Python @('-m','repair_agent','run','--data',(Join-Path $MainData 'public.jsonl'),'--out',$MainRun,
    '--config','configs\qwen-confirm-main.json','--mode','live','--live','--arms',$Arms,'--repeats','3')
if($code -ne 0){exit $code}
Run-Python @('-m','repair_agent','evaluate','--run',$MainRun,'--truth',$MainTruth) | Out-Null
Run-Python @('-m','repair_agent','analyze','--run',$MainRun) | Out-Null
Run-Python @('-m','repair_agent','replay','--run',$MainRun) | Out-Null
$MainReport='reports\progress\qwen_confirm_main_gate_20261023.json'
$code=Run-Python @('scripts\audit_confirmatory_run.py','--run',$MainRun,'--out',$MainReport,'--min-policy-differences','30')
if($code -ne 0){Log 'Full matrix completed but final gate failed; do not use as confirmatory evidence.';exit $code}
& git add $MainReport
& git commit -m 'exp: record Qwen paired confirmation matrix' *>> $Log
Log '=== confirmatory overnight complete ==='
exit 0

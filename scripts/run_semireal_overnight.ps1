$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $Root

$LogDir = Join-Path $Root 'runs\semireal_overnight_20261024'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir 'overnight.log'
Set-Content -LiteralPath $Log -Value '' -Encoding UTF8
$Arms = 'D0,D1,B0,B1,B2,B3_192,B3_truncate_192,B3_random_192,B3_384,B3_truncate_384,B3_random_384'

Add-Type -Namespace Experiment -Name NativeMethods -MemberDefinition @'
[DllImport("kernel32.dll", CharSet = CharSet.Auto, SetLastError = true)]
public static extern uint SetThreadExecutionState(uint esFlags);
'@
$ES_CONTINUOUS = [uint32]::Parse('80000000',[Globalization.NumberStyles]::HexNumber)
$ES_SYSTEM_REQUIRED = [uint32]0x00000001

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
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & python @Arguments 2>&1 | Out-File -LiteralPath $Log -Append -Encoding UTF8
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
    Log "EXIT $code"
    return $code
}

function Require-Python([string[]]$Arguments) {
    $code = Run-Python $Arguments
    if ($code -ne 0) { throw "python command failed with exit code $code" }
}

function Commit-Stage([string]$Domain,[string]$Run,[string]$Report) {
    $analysisReport = "reports\progress\qwen_semireal_${Domain}_analysis_20261024.json"
    $replayReport = "reports\progress\qwen_semireal_${Domain}_replay_20261024.json"
    Copy-Item -LiteralPath (Join-Path $Run 'analysis.json') -Destination $analysisReport -Force
    Copy-Item -LiteralPath (Join-Path $Run 'replay_summary.json') -Destination $replayReport -Force
    & git add -- $Report $analysisReport $replayReport
    & git commit -m "exp: record Qwen semireal $Domain matrix" *>> $Log
    if ($LASTEXITCODE -ne 0) { Log "WARN git commit for $Domain returned $LASTEXITCODE" }
}

function Run-Domain([string]$Domain,[string]$Data,[string]$Run,[string]$Config) {
    $Truth = Join-Path $Data 'private_truth.jsonl'
    $Report = "reports\progress\qwen_semireal_${Domain}_gate_20261024.json"
    Log "=== $Domain live matrix start ==="
    Require-Python @('-m','repair_agent','run','--data',(Join-Path $Data 'public.jsonl'),'--out',$Run,
        '--config',$Config,'--mode','live','--live','--arms',$Arms,'--repeats','1')
    Require-Python @('-m','repair_agent','evaluate','--run',$Run,'--truth',$Truth)
    Require-Python @('-m','repair_agent','analyze','--run',$Run)
    Require-Python @('-m','repair_agent','replay','--run',$Run)
    $gateCode = Run-Python @('scripts\audit_confirmatory_run.py','--run',$Run,'--out',$Report,
        '--min-policy-differences','3')
    if ($gateCode -ne 0) {
        Log "WARN $Domain scientific gate did not pass; result is retained and clearly marked."
    }
    Commit-Stage $Domain $Run $Report
    Log "=== $Domain live matrix complete ==="
}

try {
    [void][Experiment.NativeMethods]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED)
    Log '=== semireal overnight start; system sleep inhibited ==='
    if (-not (Ensure-Key 'DASHSCOPE_API_KEY')) { throw 'DASHSCOPE_API_KEY missing' }

    Require-Python @('-m','unittest','discover','-s','tests','-q')
    Require-Python @('-m','repair_agent','verify')

    Run-Domain 'bike' 'data\semireal_bike_20261024' 'runs\qwen_semireal_bike_20261024' 'configs\qwen-semireal-bike.json'
    Run-Domain 'wdbc' 'data\semireal_wdbc_20261024' 'runs\qwen_semireal_wdbc_20261024' 'configs\qwen-semireal-wdbc.json'

    Require-Python @('-m','unittest','discover','-s','tests','-q')
    Require-Python @('-m','repair_agent','verify')
    Log '=== semireal overnight complete ==='
    exit 0
}
catch {
    Log ('FATAL ' + $_.Exception.Message)
    exit 2
}
finally {
    [void][Experiment.NativeMethods]::SetThreadExecutionState($ES_CONTINUOUS)
}

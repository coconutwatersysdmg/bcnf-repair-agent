BCNF Repair Agent Experiment
============================

Research prototype for checking inclusion-maximal tuple-subset repairs under
trusted functional dependencies. Formal validity and factual truth are separate.
Default execution is OFFLINE and costs no model API fees. No GPU is required.
Python 3.11+; the experiment and tests use only the Python standard library.
Run from this source directory; there is no package-install step.

QUICK START
  python -m unittest discover -s tests -v
  python -m repair_agent verify
  python -m repair_agent smoke --out runs/demo
Windows alternative: .\run.ps1 smoke --out runs/demo

Read docs/项目运行与实验操作手册.docx for Chinese step-by-step instructions.
Read configs/qwen-pilot.json before enabling paid requests.

EXPERIMENT PROTOCOL
  D0: deterministic greedy maximal subset; source score then opaque id order.
  D1: exhaustive maximum-cardinality reference, at most 18 original records.
  B0: one model proposal, no iterative feedback.
  B1: boolean verifier feedback.
  B2: full witness envelope; if too large, explicit overflow response.
  B3: budgeted coverage-oriented witness selection.
  B3_truncate / B3_random: same-budget selection controls.
All first prompts are identical across B arms. The common feedback limit is
UTF-8 BYTES, not tokenizer-exact tokens. Context has a separate byte cap.

DATA AND EVALUATION
  python -m repair_agent generate --out data/pilot --count 100 --split pilot
  python -m repair_agent run --data data/pilot/public.jsonl --out runs/pilot-offline --repeats 3
  python -m repair_agent evaluate --run runs/pilot-offline --truth data/pilot/private_truth.jsonl
  python -m repair_agent analyze --run runs/pilot-offline
  python -m repair_agent replay --run runs/pilot-offline

Only public.jsonl is supplied to the runner; private truth is for evaluation.
Frozen runs reject changed code, data or configuration. Repeating the same run
command resumes completed jobs. Pending/uncertain network requests never retry.
Dataset folders cannot be overwritten. New settings require a new run directory.
Result matrix includes all failures and missing cases in the denominator.
Repeated trials are averaged within task; paired bootstrap clusters by base id.

LIVE MODEL USE
Create your own official provider key and set the process environment variable
DASHSCOPE_API_KEY (Qwen) or ZAI_API_KEY (BigModel). No key belongs in config/git.
The program never reads .env files and never provisions credentials.
  python -m repair_agent estimate --config configs/qwen-pilot.json --tasks 100 --repeats 3
  python -m repair_agent run --data data/pilot/public.jsonl --out runs/qwen-pilot --config configs/qwen-pilot.json --mode live --live --repeats 3
  python -m repair_agent status --run runs/qwen-pilot
Both --mode live and --live are required. No automatic HTTP retry or redirect.
Reservations survive timeout/crash. Budget is a local conservative guard based
on configured prices and token bounds; provider billing remains authoritative.
Model availability, actual prices and token accounting must be checked before use.
Do not delete a live run's ledger to evade a stopped request.

OUTPUTS
manifest.json: frozen code/config/task fingerprints.
results.jsonl: every final state and candidate/feedback trajectory.
budget.sqlite3: cache and durable budget ledger (local, git-ignored).
evaluated.csv/json: independent formal and hidden-truth metrics.
summary.csv / analysis.json / comparison.svg: summaries and uncertainty.
replay.csv: identical saved candidate traces through three checking backends.

LIMITS
Synthetic values are randomized to remove label-spelling clues. C0 has no
truth evidence; C1 provides noisy overlapping source scores. These are structural
pilot tasks, not a benchmark of semantic understanding or a publication result.
SIMULATED client is a deterministic plumbing check, not an LLM and not evidence
that B3 outperforms alternatives. Evaluate genuine models on frozen held-out
tasks and add independent domain data before making research claims.
Only strings, set semantics, trusted FDs and tuple deletion/retention are supported.
No NULL, foreign keys, cell edits, inserted facts or constraint discovery.
BCNF backend requires a BCNF schema. General FD checking is also available.
Replay reports adapter overhead; small traces do not establish speedup.
Uncertainty/retry handling favors avoiding duplicate charges over completion.

SOURCE
The nine original BCNF experiment files in vendor/legacy_bcnf are byte-for-byte
snapshots of the author's prior local experiments. vendor/snapshot.json records
hashes. New code uses an independent checker for evaluation. See NOTICE.txt.

Repository: https://github.com/coconutwatersysdmg/bcnf-repair-agent

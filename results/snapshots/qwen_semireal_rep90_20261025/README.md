# Qwen 半真实数据扩展实验快照（2026-10-25）

本目录封存 Bike Sharing 与 WDBC 两组 `rep90` 实验的可公开复核结果。快照基于提交
`f6371a40a1127e9eb1a36d23887bb67f2b6ceb22`，每组均包含 90 个基础实例、C0/C1 两条轨道、
11 个实验臂和 3 次重复，共 5940 行结果。

## 文件

- `bike_rep90_safe_results.tar.gz`：Bike Sharing 的公开任务、原始结果、评估结果、回放结果和汇总。
- `wdbc_rep90_safe_results.tar.gz`：WDBC 的公开任务、原始结果、评估结果、回放结果和汇总。

每个压缩包内有 11 个文件：`manifest.json`、`public_tasks.jsonl`、`results.jsonl`、
`run_summary.json`、`evaluated.csv`、`evaluated.json`、`analysis.json`、`summary.csv`、
`replay.csv`、`replay_summary.json`、`comparison.svg`。

为避免泄露或提交运行时状态，本快照明确排除了 API 密钥、私有真值、SQLite 预算库、
锁文件和日志。封存前已对公开内容执行敏感字段扫描，并对两个压缩包执行完整解压测试。

## SHA-256

```text
f427e222778c54acaeefe62c239dfc43eb78d1989d923ce8163ab9779a61d87f  bike_rep90_safe_results.tar.gz
08c02980a6fd49482073446535aada3211661ab9ef43e468261d23e08ce2c948  wdbc_rep90_safe_results.tar.gz
```

## 完整性说明

- WDBC：5940/5940，首轮配对审计通过。
- Bike Sharing：5940/5940；其中任务 `t_356699b8de5dbcfc837e_C1` 的重复编号 1
  遇到一次网络中断，共享缓存将该组 9 个反馈臂安全标记为 `REQUEST_UNCERTAIN`，因此原始
  快照保留该异常且首轮配对门禁未通过。后续定点恢复结果应单独保存，不覆盖本快照。

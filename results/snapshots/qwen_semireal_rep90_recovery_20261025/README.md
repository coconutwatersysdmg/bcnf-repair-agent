# Bike Sharing 定点恢复与派生矩阵快照（2026-10-25）

原始 `rep90` 矩阵中，任务 `t_356699b8de5dbcfc837e_C1` 的重复编号 1 在首轮请求时
遇到网络中断。为避免整组重跑，本快照记录了一次定点恢复：仅对该任务运行 9 个反馈臂和
重复编号 0、1，然后只用编号 1 的 9 行替换原矩阵中对应的网络异常行。

原始运行目录没有被修改；修复后数据是带显式来源记录的派生矩阵。补跑共完成 18/18 行，
16 次实际请求，无不确定请求，实际新增费用 0.019535 元。派生 Bike 矩阵为 5940/5940，
540/540 个首轮响应组配对一致，完整性门禁通过。

## 文件

- `bike_targeted_recovery_safe_results.tar.gz`：定点补跑的公开任务、原始响应、评估和回放结果。
- `bike_rep90_recovered_safe_results.tar.gz`：只替换 9 个网络异常行后的完整派生矩阵及替换来源。

两个压缩包均排除了 API 密钥、私有真值、SQLite 预算库、锁文件和日志，并已通过完整解压测试。

## SHA-256

```text
5d6020eb095ab4bd35121bed0e4236dc131682e51231c6874ab488cf6df26f0a  bike_targeted_recovery_safe_results.tar.gz
aedc0a16e4f6540eb7fb99c9ff5c46827f08975626f64fae9b2611df219c9384  bike_rep90_recovered_safe_results.tar.gz
```

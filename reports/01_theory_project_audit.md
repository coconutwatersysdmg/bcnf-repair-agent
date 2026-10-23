# 01 项目审计（2026-10-22）

依据 `Cursor实验执行Prompt_理论加强版_20261021.md` 第二节离线验收。本机未启动真实模型请求。

## 环境

| 项 | 结果 |
| --- | --- |
| Python | 3.12.7（`python`）/ 3.12.10（`py -3`） |
| 核心依赖 | 标准库；无需 pip 安装 |
| `DASHSCOPE_API_KEY` | 未设置 |
| `ZAI_API_KEY` | 已设置（本审计未调用） |
| vendor 快照 | `python -m repair_agent verify` → `{"ok": true, "changed": []}` |

## 本次验收命令与结果

```powershell
python -m unittest discover -s tests -v
# Ran 29 tests in ~2.8s — OK

python -m repair_agent verify
# {"ok": true, "changed": []}

python -m repair_agent smoke --out runs/theory_acceptance_20261022
# completed=300/300, mode=SIMULATED, cost_cny=0, attempts=0
```

额外端到端演练（仍为 SIMULATED，费用 0）：

```powershell
python -m repair_agent generate --out data/theory_dev_demo_20261022 --count 12 --entities 6 --seed 2026102201 --split dev
python -m repair_agent run --data data/theory_dev_demo_20261022/public.jsonl --out runs/theory_dev_demo_20261022 --arms D0,B0,B1,B2,B3,B3_truncate,B3_random --repeats 1
python -m repair_agent evaluate --run runs/theory_dev_demo_20261022 --truth data/theory_dev_demo_20261022/private_truth.jsonl
python -m repair_agent analyze --run runs/theory_dev_demo_20261022
python -m repair_agent status --run runs/theory_dev_demo_20261022
```

结果：84/84 完成；D0 与多轮 B 组可落盘；分析含 B2–B1、B3–截断、B3–随机配对区间；账本 `cost_cny=0`。

**重要：** SIMULATED 仅验证工程管道，不可写入论文主结果表。

## 已完成

- 离线 CLI：generate / run(simulate) / evaluate / analyze / replay / smoke / verify / status / estimate
- 双开关 live：`--mode live --live`；缺任一不发网
- 本地预算账本 `budget.sqlite3`；不确定请求不自动重试
- 公开/私有数据隔离；oracle 与 legacy 快照校验
- 29 个单元测试覆盖预算、HTTP 429、非法输出、续跑等

## 已知缺口（对照 Prompt，未在本轮改代码）

1. **在线路径**主要为静态判定；增量主要用于 `replay`，不能虚报在线增量已完成。
2. **B3** 为“新增覆盖优先 + 字节/稳定表示破平局”，无收益/字节排序与固定近似比。
3. **B2** 生成完整见证；超总上下文多在后续调用前终止；需核对是否有独立可测试的超限状态命名。
4. **analyze** 配对 bootstrap 仍以形式修复率（pass）为主；`valid_f1`、token、成本差值等需扩充。
5. **C0/C1** 现生成器按单元格轮转，非同底表配对副本；非完整析因。
6. **estimate** 仍硬编码 `×16`（四组 B0–B3）；六组上界应为每题约 26 次，费用估算会偏低。
7. **静态 replay** 含适配/快照核验时间；缺纯内核计时与结构消融对照（Singleton-FullScan 等）。
8. **真实来源数据**、配对任务生成器、正式矩阵冻结方案尚未落地。
9. 配置中的模型 ID / 标价日期需在真实预实验前按官网重核；“free”不等于无限额度。

## 真实预实验门槛（未授权，未执行）

Prompt 要求用户明确说「开始真实模型预实验」后，才可在累计 ≤20 元人民币内调用 API。当前状态：

- 缺 `DASHSCOPE_API_KEY` → Qwen 无法 live
- 有 `ZAI_API_KEY` → GLM 可尝试，但仍需口头授权
- 建议先 2–3 题连通性试跑，再 30 题预实验

## 版本备注

用户提供的 `Cursor实验执行Prompt_20261019.md` 已注明被 `Cursor实验执行Prompt_理论加强版_20261021.md` 替代；本审计按 20261021 版执行。

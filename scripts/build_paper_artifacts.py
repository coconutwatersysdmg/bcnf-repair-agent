"""Build frozen paper tables, paired statistics, SVG figures, and the final experiment report."""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean


ARM_ORDER = [
    "D0", "D1", "B0", "B1", "B2",
    "B3_192", "B3_truncate_192", "B3_random_192",
    "B3_384", "B3_truncate_384", "B3_random_384",
]
ARM_PAIRS = [
    ("B2", "B1"),
    ("B3_192", "B3_truncate_192"),
    ("B3_192", "B3_random_192"),
    ("B3_384", "B3_truncate_384"),
    ("B3_384", "B3_random_384"),
]


def metric_value(row, metric):
    if metric == "repair_rate":
        return float(bool(row.get("is_repair", row.get("status") == "PASS")))
    if metric == "valid_f1":
        return float(row.get("f1", 0)) if metric_value(row, "repair_rate") else 0.0
    raise ValueError("unknown metric")


def validate_matrix(rows, manifest):
    expected = len(manifest["task_hashes"]) * len(manifest["arms"]) * manifest["repeats"]
    keys = [(row["task_id"], row["arm"], row["repeat"]) for row in rows]
    if len(rows) != expected:
        raise ValueError(f"incomplete matrix: {len(rows)}/{expected}")
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate matrix keys")
    if set(row["arm"] for row in rows) != set(manifest["arms"]):
        raise ValueError("matrix arms differ from manifest")
    return expected


def _bootstrap_effect(differences, controls, draws, seed):
    values = [differences[key] for key in sorted(differences)]
    control_values = [controls[key] for key in sorted(differences)]
    if not values:
        raise ValueError("no paired base instances")
    effect = mean(values)
    control = mean(control_values)
    rng = random.Random(seed)
    boot = []
    n = len(values)
    for _ in range(draws):
        boot.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    boot.sort()
    low = boot[int(draws * 0.025)]
    high = boot[min(draws - 1, int(draws * 0.975))]
    lower_tail = (sum(value <= 0 for value in boot) + 1) / (draws + 1)
    upper_tail = (sum(value >= 0 for value in boot) + 1) / (draws + 1)
    return {
        "n_base_instances": n,
        "absolute_difference": effect,
        "relative_difference": None if control == 0 else effect / abs(control),
        "ci95_low": low,
        "ci95_high": high,
        "p_value": min(1.0, 2 * min(lower_tail, upper_tail)),
        "draws": draws,
        "ci_method": "paired base-instance cluster bootstrap; repeats averaged before resampling",
    }


def paired_arm_effect(rows, left, right, metric, draws=10000, seed=20261025):
    lookup = {(row["task_id"], row["repeat"], row["arm"]): row for row in rows}
    differences = defaultdict(list)
    controls = defaultdict(list)
    for row in rows:
        if row["arm"] != left:
            continue
        other = lookup.get((row["task_id"], row["repeat"], right))
        if other is None:
            continue
        base = row["base_instance_id"]
        differences[base].append(metric_value(row, metric) - metric_value(other, metric))
        controls[base].append(metric_value(other, metric))
    averaged = {base: mean(values) for base, values in differences.items()}
    averaged_controls = {base: mean(controls[base]) for base in averaged}
    return _bootstrap_effect(averaged, averaged_controls, draws, seed)


def paired_track_effect(rows, arm, metric, draws=10000, seed=20261025):
    lookup = {(row["base_instance_id"], row["repeat"], row["arm"], row["track"]): row for row in rows}
    differences = defaultdict(list)
    controls = defaultdict(list)
    bases = sorted({row["base_instance_id"] for row in rows if row["arm"] == arm})
    repeats = sorted({row["repeat"] for row in rows if row["arm"] == arm})
    for base in bases:
        for repeat in repeats:
            c0 = lookup.get((base, repeat, arm, "C0"))
            c1 = lookup.get((base, repeat, arm, "C1"))
            if c0 is None or c1 is None:
                continue
            differences[base].append(metric_value(c1, metric) - metric_value(c0, metric))
            controls[base].append(metric_value(c0, metric))
    averaged = {base: mean(values) for base, values in differences.items()}
    averaged_controls = {base: mean(controls[base]) for base in averaged}
    return _bootstrap_effect(averaged, averaged_controls, draws, seed)


def holm_adjust(p_values):
    order = sorted(range(len(p_values)), key=lambda index: p_values[index])
    adjusted = [0.0] * len(p_values)
    running = 0.0
    total = len(p_values)
    for rank, index in enumerate(order):
        running = max(running, min(1.0, (total - rank) * p_values[index]))
        adjusted[index] = running
    return [
        {"p_value": p_values[index], "p_holm": adjusted[index], "reject_0_05": adjusted[index] < 0.05}
        for index in range(len(p_values))
    ]


def _seed(*parts):
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:12], 16)


def _write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _load_run(label, path, gate_path):
    path = Path(path)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    rows = json.loads((path / "evaluated.json").read_text(encoding="utf-8"))
    raw = [json.loads(line) for line in (path / "results.jsonl").read_text(encoding="utf-8").splitlines() if line]
    gate = json.loads(Path(gate_path).read_text(encoding="utf-8"))
    if not gate.get("ok"):
        raise ValueError(f"scientific gate failed for {label}")
    validate_matrix(rows, manifest)
    if len(raw) != len(rows):
        raise ValueError(f"raw/evaluated row mismatch for {label}")
    return {"label": label, "path": path, "manifest": manifest, "rows": rows, "raw": raw, "gate": gate,
            "summary": json.loads((path / "run_summary.json").read_text(encoding="utf-8"))}


def _main_results(run):
    manifest = run["manifest"]
    config = manifest["config"]
    output = []
    for arm in ARM_ORDER:
        members = [row for row in run["rows"] if row["arm"] == arm]
        if not members:
            continue
        output.append({
            "dataset": run["label"], "arm": arm, "mode": members[0]["mode"],
            "n_tasks": len({row["task_id"] for row in members}),
            "n_base_instances": len({row["base_instance_id"] for row in members}),
            "repeats": manifest["repeats"], "n_results": len(members),
            "repair_rate": mean(metric_value(row, "repair_rate") for row in members),
            "valid_f1": mean(metric_value(row, "valid_f1") for row in members),
            "truth_precision": mean(float(row.get("precision", 0)) for row in members),
            "truth_recall": mean(float(row.get("recall", 0)) for row in members),
            "truth_f1": mean(float(row.get("f1", 0)) for row in members),
            "failure_count": sum(not bool(row.get("is_repair")) for row in members),
            "failures_in_denominator": True, "model": config["model"],
            "prompt_version": config["prompt_version"], "feedback_bytes": config["feedback_bytes"],
            "run_date": "2026-10-25" if "semireal" in run["label"] else "2026-10-23",
            "ci_method": "descriptive point estimate; paired inferential CIs are in paired_effects.csv",
        })
    return output


def _paired_effects(run, draws):
    effects = []
    arms = [arm for arm in ARM_ORDER if arm in run["manifest"]["arms"]]
    for metric in ("repair_rate", "valid_f1"):
        for left, right in ARM_PAIRS:
            result = paired_arm_effect(run["rows"], left, right, metric, draws, _seed(run["label"], metric, left, right))
            effects.append(dict(dataset=run["label"], metric=metric, comparison_type="arm",
                                comparison=f"{left}-{right}", left=left, right=right, **result))
        for arm in arms:
            result = paired_track_effect(run["rows"], arm, metric, draws, _seed(run["label"], metric, arm, "C1-C0"))
            effects.append(dict(dataset=run["label"], metric=metric, comparison_type="track",
                                comparison=f"{arm}:C1-C0", left="C1", right="C0", arm=arm, **result))
    for metric in ("repair_rate", "valid_f1"):
        subset = [effect for effect in effects if effect["metric"] == metric]
        corrected = holm_adjust([effect["p_value"] for effect in subset])
        for effect, values in zip(subset, corrected):
            effect.update(values)
            effect["ci_crosses_zero"] = effect["ci95_low"] <= 0 <= effect["ci95_high"]
            effect["holm_family"] = f"{run['label']}:{metric}:all_preregistered_comparisons"
    config = run["manifest"]["config"]
    for effect in effects:
        effect.update(n_tasks=len(run["manifest"]["task_hashes"]), repeats=run["manifest"]["repeats"],
                      failures_in_denominator=True, model=config["model"], prompt_version=config["prompt_version"],
                      feedback_bytes=config["feedback_bytes"],
                      run_date="2026-10-25" if "semireal" in run["label"] else "2026-10-23")
    return effects


def _failure_breakdown(run):
    output = []
    for arm in ARM_ORDER:
        members = [row for row in run["rows"] if row["arm"] == arm]
        counts = Counter(row["status"] for row in members)
        for status, count in sorted(counts.items()):
            output.append({"dataset": run["label"], "arm": arm, "status": status, "count": count,
                           "rate": count / len(members), "n_results": len(members),
                           "n_tasks": len({row["task_id"] for row in members}),
                           "n_base_instances": len({row["base_instance_id"] for row in members}),
                           "repeats": run["manifest"]["repeats"], "failures_in_denominator": True,
                           "model": run["manifest"]["config"]["model"],
                           "prompt_version": run["manifest"]["config"]["prompt_version"],
                           "feedback_bytes": run["manifest"]["config"]["feedback_bytes"],
                           "run_date": "2026-10-25" if "semireal" in run["label"] else "2026-10-23",
                           "ci_method": "not applicable (descriptive status counts)"})
    return output


def _cost_latency(run):
    output = []
    actual = run["summary"].get("ledger", {})
    actual_attempts = actual.get("attempts")
    derivation = run["manifest"].get("derivation")
    if actual_attempts is None and derivation:
        source = json.loads((Path(derivation["source_run"]) / "run_summary.json").read_text(encoding="utf-8"))
        recovery = json.loads((Path(derivation["recovery_run"]) / "run_summary.json").read_text(encoding="utf-8"))
        actual_attempts = source["ledger"]["attempts"] + recovery["ledger"]["attempts"]
    config = run["manifest"]["config"]
    output.append({"dataset": run["label"], "arm": "__ALL__", "n_results": len(run["raw"]),
                   "logical_calls": sum(row.get("rounds", 0) for row in run["raw"]),
                   "attributed_network_attempts": sum(row.get("network_attempts", 0) for row in run["raw"]),
                   "attributed_equivalent_cost_cny": sum(row.get("billed_cny", 0) for row in run["raw"]),
                   "actual_network_attempts": actual_attempts,
                   "actual_ledger_cost_cny": actual.get("cost_cny", 0), "mean_elapsed_seconds": "",
                   "mean_checker_seconds": "", "n_tasks": len(run["manifest"]["task_hashes"]),
                   "n_base_instances": len({row["base_instance_id"] for row in run["raw"]}),
                   "repeats": run["manifest"]["repeats"], "failures_in_denominator": True,
                   "model": config["model"], "prompt_version": config["prompt_version"],
                   "feedback_bytes": config["feedback_bytes"],
                   "run_date": "2026-10-25" if "semireal" in run["label"] else "2026-10-23",
                   "ci_method": "not applicable (accounting and latency descriptives)"})
    for arm in ARM_ORDER:
        members = [row for row in run["raw"] if row["arm"] == arm]
        if not members:
            continue
        output.append({"dataset": run["label"], "arm": arm, "n_results": len(members),
                       "logical_calls": sum(row.get("rounds", 0) for row in members),
                       "attributed_network_attempts": sum(row.get("network_attempts", 0) for row in members),
                       "attributed_equivalent_cost_cny": sum(row.get("billed_cny", 0) for row in members),
                       "actual_network_attempts": "", "actual_ledger_cost_cny": "",
                       "mean_elapsed_seconds": mean(row.get("elapsed_seconds", 0) for row in members),
                       "mean_checker_seconds": mean(row.get("checker_seconds", 0) for row in members),
                       "n_tasks": len({row["task_id"] for row in members}),
                       "n_base_instances": len({row["base_instance_id"] for row in members}),
                       "repeats": run["manifest"]["repeats"], "failures_in_denominator": True,
                       "model": config["model"], "prompt_version": config["prompt_version"],
                       "feedback_bytes": config["feedback_bytes"],
                       "run_date": "2026-10-25" if "semireal" in run["label"] else "2026-10-23",
                       "ci_method": "not applicable (accounting and latency descriptives)"})
    return output


def _svg_bar_panels(main_rows, metric, title, path, arms=None):
    arms = arms or ARM_ORDER
    datasets = list(dict.fromkeys(row["dataset"] for row in main_rows))
    width, height, panel_w = 1260, 610, 390
    colors = {"D0": "#64748b", "D1": "#94a3b8", "B0": "#f59e0b", "B1": "#ef4444", "B2": "#10b981"}
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="#ffffff"/>',
             f'<text x="36" y="38" font-family="Arial,sans-serif" font-size="22" font-weight="700" fill="#0f172a">{html.escape(title)}</text>',
             '<text x="36" y="62" font-family="Arial,sans-serif" font-size="12" fill="#64748b">Failures remain in the denominator · 90 base instances · 3 repeats</text>']
    for panel, dataset in enumerate(datasets):
        x0 = 42 + panel * panel_w
        y0, plot_h = 105, 390
        rows = {row["arm"]: row for row in main_rows if row["dataset"] == dataset}
        parts.append(f'<text x="{x0}" y="92" font-family="Arial,sans-serif" font-size="15" font-weight="700" fill="#334155">{html.escape(dataset)}</text>')
        for tick in range(6):
            y = y0 + plot_h - tick * plot_h / 5
            parts.extend([f'<line x1="{x0}" y1="{y:.1f}" x2="{x0+340}" y2="{y:.1f}" stroke="#e2e8f0"/>',
                          f'<text x="{x0-8}" y="{y+4:.1f}" text-anchor="end" font-family="Arial" font-size="10" fill="#64748b">{tick*20}%</text>'])
        bar_w = 24
        gap = (340 - bar_w * len(arms)) / max(1, len(arms) - 1)
        for index, arm in enumerate(arms):
            if arm not in rows:
                continue
            value = float(rows[arm][metric])
            x = x0 + index * (bar_w + gap)
            h = value * plot_h
            color = colors.get(arm, "#2563eb" if "192" in arm else "#7c3aed")
            parts.extend([f'<rect x="{x:.1f}" y="{y0+plot_h-h:.1f}" width="{bar_w}" height="{h:.1f}" rx="3" fill="{color}"/>',
                          f'<text transform="translate({x+bar_w/2:.1f},{y0+plot_h+14}) rotate(55)" text-anchor="start" font-family="Arial" font-size="9" fill="#475569">{html.escape(arm)}</text>'])
    parts.append('</svg>')
    path.write_text("\n".join(parts), encoding="utf-8")


def _svg_effects(effects, path):
    selected = [effect for effect in effects if effect["metric"] == "repair_rate" and effect["comparison_type"] == "track"
                and effect.get("arm") in {"B0", "B1", "B2", "B3_192", "B3_384"}]
    width, row_h, top = 1120, 30, 88
    height = top + len(selected) * row_h + 45
    max_abs = max(0.1, max(max(abs(effect["ci95_low"]), abs(effect["ci95_high"])) for effect in selected) * 1.15)
    x_left, x_right = 430, 1060
    scale = (x_right - x_left) / (2 * max_abs)
    zero = (x_left + x_right) / 2
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="white"/>',
             '<text x="30" y="34" font-family="Arial" font-size="22" font-weight="700" fill="#0f172a">Paired evidence effect on formal repair rate</text>',
             '<text x="30" y="58" font-family="Arial" font-size="12" fill="#64748b">C1 − C0 · base-instance cluster bootstrap · 95% CI</text>',
             f'<line x1="{zero:.1f}" y1="72" x2="{zero:.1f}" y2="{height-28}" stroke="#64748b" stroke-dasharray="4 4"/>']
    for index, effect in enumerate(selected):
        y = top + index * row_h
        label = f'{effect["dataset"]} · {effect["arm"]}'
        low = zero + effect["ci95_low"] * scale
        high = zero + effect["ci95_high"] * scale
        point = zero + effect["absolute_difference"] * scale
        color = "#0f766e" if effect["reject_0_05"] and not effect["ci_crosses_zero"] else "#64748b"
        parts.extend([f'<text x="30" y="{y+4}" font-family="Arial" font-size="11" fill="#334155">{html.escape(label)}</text>',
                      f'<line x1="{low:.1f}" y1="{y}" x2="{high:.1f}" y2="{y}" stroke="{color}" stroke-width="2"/>',
                      f'<circle cx="{point:.1f}" cy="{y}" r="4" fill="{color}"/>',
                      f'<text x="1070" y="{y+4}" font-family="Arial" font-size="10" fill="#475569">{effect["absolute_difference"]:+.3f}</text>'])
    parts.append('</svg>')
    path.write_text("\n".join(parts), encoding="utf-8")


def _fmt_effect(effect):
    significance = "Holm 校正后显著" if effect["reject_0_05"] and not effect["ci_crosses_zero"] else "区间跨 0 或 Holm 校正后不显著"
    return (f'{effect["absolute_difference"]:+.3f}（95% CI '
            f'[{effect["ci95_low"]:+.3f}, {effect["ci95_high"]:+.3f}]，p_Holm={effect["p_holm"]:.4f}；{significance}）')


def _build_report(runs, main_rows, effects, benchmark_path, out):
    by_key = {(row["dataset"], row["arm"]): row for row in main_rows}
    effect_key = {(row["dataset"], row["metric"], row["comparison"]): row for row in effects}
    costs = {run["label"]: float(run["summary"].get("ledger", {}).get("cost_cny", 0)) for run in runs}
    benchmark = list(csv.DictReader(Path(benchmark_path).open(encoding="utf-8-sig")))
    agreement = min(float(row["agreement_rate"]) for row in benchmark)
    lines = [
        "# 论文实验总报告（确认版，2026-10-25）", "",
        "> 本报告由冻结的原始结果自动生成。形式修复成功表示输出满足函数依赖且包含极大，不等于事实真值正确。", "",
        "## 实验范围与可复核性", "",
        "三组确认矩阵均使用 Qwen3.7-Flash、90 个 base instances、C0/C1 同底表、11 个实验臂和 3 次重复；每组 5940 行。失败状态全部保留在分母。配对效应先在任务内平均重复，再按 base instance 聚类进行 10,000 次 bootstrap；预注册主比较在每个数据集与指标内做 Holm 校正。", "",
        "Bike 原矩阵的一组首轮请求发生网络中断，已用独立定点补跑替换对应 9 行形成派生矩阵；原始矩阵与补跑均单独封存，派生矩阵的 540/540 个首轮响应组配对一致。", "",
        "## 旧 Qwen 探索性实验", "",
        "旧矩阵完成 6300/6300，观察到 B2 相对 B1 的探索性修复率提升约 44.78 个百分点；但旧 B3 的 1600 字节预算从未真正生效、不同策略首轮回答不配对、C0/C1 也不是同底表。因此这部分只作为预实验和工程可行性证据，不进入确认性主比较。", "",
        "## 修正后的合成确认性实验", "",
    ]
    synth = "synthetic_confirmation"
    lines += [
        f'- B1 修复率 {by_key[(synth,"B1")]["repair_rate"]:.1%}，B2 为 {by_key[(synth,"B2")]["repair_rate"]:.1%}。',
        f'- B2 − B1：{_fmt_effect(effect_key[(synth,"repair_rate","B2-B1")])}',
        f'- 192 字节覆盖优先 − 截断：{_fmt_effect(effect_key[(synth,"repair_rate","B3_192-B3_truncate_192")])}',
        f'- 384 字节覆盖优先 − 随机：{_fmt_effect(effect_key[(synth,"repair_rate","B3_384-B3_random_384")])}', "",
        "## 半真实外部验证", "",
    ]
    for dataset, title in (("semireal_bike", "Bike Sharing"), ("semireal_wdbc", "WDBC")):
        lines += [
            f'### {title}', "",
            f'- B1 修复率 {by_key[(dataset,"B1")]["repair_rate"]:.1%}，B2 为 {by_key[(dataset,"B2")]["repair_rate"]:.1%}。',
            f'- B2 − B1：{_fmt_effect(effect_key[(dataset,"repair_rate","B2-B1")])}',
            f'- B2 的 C1 − C0：{_fmt_effect(effect_key[(dataset,"repair_rate","B2:C1-C0")])}', "",
        ]
    lines += [
        "两套半真实数据都基于显式唯一标识符构造 BCNF 键依赖，因此支持的是‘受控键冲突修复’外部有效性，而不是所有业务函数依赖场景。WDBC 与 Bike 的来源证据效应应分别解释，不合并成单一通过率。", "",
        "## BCNF 离线效率实验", "",
        f'BCNF、通用 FD 与独立参考后端在 6000 个状态上的最低一致率为 {agreement:.1%}。完整规模、冲突率、构建/判定/诊断耗时与峰值内存见 `results/benchmarks/bcnf_backend_20261024/bcnf_backend_summary.csv`；论文图见 `reports/figures/bcnf_backend_scaling.svg`。', "",
        "## 费用与未完成项", "",
        f'- 合成确认矩阵实际账本费用：{costs[synth]:.6f} 元。',
        f'- Bike（含定点恢复）实际费用：{costs["semireal_bike"]:.6f} 元。',
        f'- WDBC 实际费用：{costs["semireal_wdbc"]:.6f} 元。',
        f'- 三组确认/外部验证合计：{sum(costs.values()):.6f} 元。',
        "- GLM-4.7-Flash 与 GLM-4.5-Air 的新鲜单请求探针持续返回 HTTP 429，未扩展为第二模型矩阵；不得写成已完成跨模型复现。", "",
        "## 可用于论文的产物", "",
        "- `reports/tables/main_results.csv`：主结果与样本量。",
        "- `reports/tables/paired_effects.csv`：10,000 次配对 bootstrap、相对差、95% CI、原始 p 与 Holm 校正。",
        "- `reports/tables/failure_breakdown.csv`：失败状态计数及分母。",
        "- `reports/tables/cost_latency.csv`：实际账本与归因等价成本、调用和时延。",
        "- `reports/figures/repair_rate_by_arm.svg`、`valid_f1_by_arm.svg`、`c0_c1_paired_effect.svg`、`budget_policy_effect.svg`：可编辑矢量图。", "",
        "## 结论边界", "",
        "可以据此报告：形式约束反馈相对仅布尔反馈的确认性效应、有限反馈预算策略的差异、同底表来源证据的配对效应，以及 BCNF 专用检查后端的正确性与效率。不能据此声称模型恢复了客观事实、覆盖所有关系模式、或已经完成跨模型复现。", "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")


def build(root, draws=10000):
    root = Path(root)
    specs = [
        ("synthetic_confirmation", root / "runs/qwen_confirm_paired_20261023", root / "reports/progress/qwen_confirm_main_gate_20261023.json"),
        ("semireal_bike", root / "runs/qwen_semireal_bike_rep90_recovered_20261025", root / "reports/progress/qwen_semireal_bike_rep90_recovered_gate_20261025.json"),
        ("semireal_wdbc", root / "runs/qwen_semireal_wdbc_rep90_20261025", root / "reports/progress/qwen_semireal_wdbc_rep90_gate_20261025.json"),
    ]
    runs = [_load_run(*spec) for spec in specs]
    main_rows = [row for run in runs for row in _main_results(run)]
    effects = [row for run in runs for row in _paired_effects(run, draws)]
    failures = [row for run in runs for row in _failure_breakdown(run)]
    costs = [row for run in runs for row in _cost_latency(run)]
    tables = root / "reports/tables"
    figures = root / "reports/figures"
    tables.mkdir(parents=True, exist_ok=True)
    figures.mkdir(parents=True, exist_ok=True)
    _write_csv(tables / "main_results.csv", main_rows, list(main_rows[0]))
    effect_fields = ["dataset", "metric", "comparison_type", "comparison", "left", "right", "arm",
                     "n_tasks", "n_base_instances", "repeats", "failures_in_denominator", "model",
                     "prompt_version", "feedback_bytes", "run_date",
                     "absolute_difference", "relative_difference", "ci95_low", "ci95_high",
                     "p_value", "p_holm", "reject_0_05", "ci_crosses_zero", "draws", "ci_method", "holm_family"]
    _write_csv(tables / "paired_effects.csv", effects, effect_fields)
    _write_csv(tables / "failure_breakdown.csv", failures, list(failures[0]))
    _write_csv(tables / "cost_latency.csv", costs, list(costs[0]))
    _svg_bar_panels(main_rows, "repair_rate", "Formal repair rate by arm", figures / "repair_rate_by_arm.svg")
    _svg_bar_panels(main_rows, "valid_f1", "Valid F1 by arm", figures / "valid_f1_by_arm.svg")
    _svg_effects(effects, figures / "c0_c1_paired_effect.svg")
    budget_arms = ["B3_192", "B3_truncate_192", "B3_random_192", "B3_384", "B3_truncate_384", "B3_random_384"]
    _svg_bar_panels(main_rows, "repair_rate", "Feedback-budget policy effect", figures / "budget_policy_effect.svg", budget_arms)
    _build_report(runs, main_rows, effects, root / "results/benchmarks/bcnf_backend_20261024/bcnf_backend_summary.csv",
                  root / "reports/论文实验总报告_确认版_20261023.md")
    return {"runs": len(runs), "main_rows": len(main_rows), "paired_effects": len(effects),
            "failure_rows": len(failures), "cost_rows": len(costs), "draws": draws}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--draws", type=int, default=10000)
    args = parser.parse_args()
    if args.draws < 10000:
        raise ValueError("final paper analysis requires at least 10000 bootstrap draws")
    print(json.dumps(build(args.root, args.draws), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Reproducible BCNF backend scaling benchmark with crash-safe CSV output."""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import platform
import statistics
import sys
import time
import tracemalloc
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from repair_agent.checker import decision as generic_decision
from repair_agent.legacy import _api


RAW_FIELDS = [
    "family", "row_count", "conflict_ratio", "seed", "algorithm", "repeat",
    "status", "is_repair", "candidate_consistent", "decision_ns", "build_ns",
    "check_ns", "diagnose_ns", "incremental_remove_ns", "incremental_add_ns",
    "peak_bytes", "index_count",
]


def _modules():
    types, bcnf_index, incremental = _api()
    from algorithms.fd_hash import is_subset_repair_fd_hash
    from algorithms.singleton_fullscan import is_subset_repair_singleton_fullscan

    return types, bcnf_index, incremental, is_subset_repair_fd_hash, is_subset_repair_singleton_fullscan


def build_instance(row_count: int, family: str, conflict_ratio: float, seed: int):
    if row_count < 2 or family not in {"single", "dual", "composite"}:
        raise ValueError("invalid benchmark instance")
    if not 0 <= conflict_ratio < 0.5:
        raise ValueError("conflict_ratio must be in [0, 0.5)")
    types, _, _, _, _ = _modules()
    if family == "single":
        attrs = ("A", "B", "C")
        lhses = (("A",),)
    elif family == "dual":
        attrs = ("A", "B", "C", "D")
        lhses = (("A",), ("B",))
    else:
        attrs = ("A", "B", "C", "D")
        lhses = (("A", "B"),)
    schema = types.RelationSchema(
        attributes=attrs,
        fds=tuple(types.FD(lhs, attrs) for lhs in lhses),
        name=f"bench_{family}",
    )
    dirty_count = min(int(round(row_count * conflict_ratio)), row_count // 3)
    clean_count = row_count - dirty_count
    clean = []
    salt = seed * 1_000_003
    for index in range(clean_count):
        if family == "single":
            row = (f"a{index}", f"b{salt + index}", f"c{index}")
        else:
            row = (f"a{index}", f"b{index}", f"c{salt + index}", f"d{index}")
        clean.append(row)
    dirty = []
    for index in range(dirty_count):
        base = clean[index % clean_count]
        if family == "single":
            row = (base[0], f"dirty_b{salt + index}", f"dirty_c{index}")
        elif family == "dual":
            row = (base[0], f"dirty_b{salt + index}", f"dirty_c{index}", f"dirty_d{index}")
        else:
            row = (base[0], base[1], f"dirty_c{salt + index}", f"dirty_d{index}")
        dirty.append(row)
    rows = clean + dirty
    return schema, rows, clean


def _task(schema, rows, retained):
    records = [{"id": f"r{i}", "values": list(row)} for i, row in enumerate(rows)]
    ids = [f"r{i}" for i in range(len(retained))]
    return {
        "task_id": "benchmark", "base_instance_id": "benchmark", "split": "test",
        "schema": {"name": schema.name, "attributes": list(schema.attributes),
                   "fds": [fd.to_json() for fd in schema.fds]},
        "records": records, "initial_keep_ids": ids, "source_evidence": {},
        "category": "benchmark", "family": "benchmark", "track": "C0",
    }, ids


def check_all_backends(schema, rows, retained, include_fullscan: bool):
    _, bcnf_index, _, fd_hash, fullscan = _modules()
    results = {
        "bcnf_index": bcnf_index.is_subset_repair_bcnf_index(schema, rows, retained),
        "fd_hash": fd_hash(schema, rows, retained),
    }
    if include_fullscan:
        results["singleton_fullscan"] = fullscan(schema, rows, retained)
    return results


def _measure_peak(callable_):
    tracemalloc.start()
    try:
        callable_()
        _, peak = tracemalloc.get_traced_memory()
        return peak
    finally:
        tracemalloc.stop()


def _percentile(values, quantile):
    ordered = sorted(values)
    if not ordered:
        return 0
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _bench_algorithm(name, schema, rows, retained, repeat):
    _, bcnf_index, incremental, fd_hash, fullscan = _modules()
    task, retained_ids = _task(schema, rows, retained)
    build_ns = check_ns = diagnose_ns = remove_ns = add_ns = 0
    if name == "bcnf_index":
        checker = bcnf_index.BCNFRepairChecker(schema)
        start = time.perf_counter_ns()
        result = checker.check(rows, retained)
        decision_ns = time.perf_counter_ns() - start
        build_ns = int(result.build_time_sec * 1e9)
        check_ns = int(result.check_time_sec * 1e9)
        if len(rows) > len(retained):
            start = time.perf_counter_ns()
            checker.find_conflict_witness(rows[len(retained)])
            diagnose_ns = time.perf_counter_ns() - start
        peak = _measure_peak(lambda: bcnf_index.is_subset_repair_bcnf_index(schema, rows, retained)) if repeat == 0 else 0
    elif name == "fd_hash":
        start = time.perf_counter_ns()
        result = fd_hash(schema, rows, retained)
        decision_ns = time.perf_counter_ns() - start
        build_ns = int(result.build_time_sec * 1e9)
        check_ns = int(result.check_time_sec * 1e9)
        peak = _measure_peak(lambda: fd_hash(schema, rows, retained)) if repeat == 0 else 0
    elif name == "singleton_fullscan":
        start = time.perf_counter_ns()
        result = fullscan(schema, rows, retained)
        decision_ns = time.perf_counter_ns() - start
        check_ns = int(result.check_time_sec * 1e9)
        peak = _measure_peak(lambda: fullscan(schema, rows, retained)) if repeat == 0 else 0
    elif name == "repair_agent_generic":
        start = time.perf_counter_ns()
        verdict = generic_decision(task, retained_ids, "generic")
        decision_ns = time.perf_counter_ns() - start
        result = type("Result", (), {"is_repair": verdict["is_repair"],
                                      "candidate_consistent": verdict["consistent"],
                                      "index_count": len(schema.fds)})()
        peak = _measure_peak(lambda: generic_decision(task, retained_ids, "generic")) if repeat == 0 else 0
    elif name == "incremental":
        start = time.perf_counter_ns()
        state = incremental.BCNFRepairState(schema, rows, retained)
        decision_ns = time.perf_counter_ns() - start
        probe = retained[0]
        state.reset_work_counters()
        start = time.perf_counter_ns()
        state.move_retained_to_deleted(probe)
        remove_ns = time.perf_counter_ns() - start
        start = time.perf_counter_ns()
        state.move_deleted_to_retained(probe)
        add_ns = time.perf_counter_ns() - start
        result = type("Result", (), {"is_repair": state.is_repair(),
                                      "candidate_consistent": state.candidate_consistent(),
                                      "index_count": len(state.index_keys)})()
        peak = _measure_peak(lambda: incremental.BCNFRepairState(schema, rows, retained)) if repeat == 0 else 0
    else:
        raise ValueError("unknown algorithm")
    return {
        "status": "OK", "is_repair": result.is_repair,
        "candidate_consistent": result.candidate_consistent,
        "decision_ns": decision_ns, "build_ns": build_ns, "check_ns": check_ns,
        "diagnose_ns": diagnose_ns, "incremental_remove_ns": remove_ns,
        "incremental_add_ns": add_ns, "peak_bytes": peak,
        "index_count": getattr(result, "index_count", 0),
    }


def _write_summary(raw_path: Path, summary_path: Path):
    groups = defaultdict(list)
    with raw_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["status"] != "OK":
                continue
            key = (row["family"], row["row_count"], row["conflict_ratio"], row["algorithm"])
            groups[key].append(row)
    fields = ["family", "row_count", "conflict_ratio", "algorithm", "n",
              "median_decision_ns", "p95_decision_ns", "median_build_ns",
              "median_check_ns", "median_diagnose_ns", "median_incremental_remove_ns",
              "median_incremental_add_ns", "max_peak_bytes", "agreement_rate"]
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for key in sorted(groups, key=lambda x: (x[0], int(x[1]), float(x[2]), x[3])):
            rows = groups[key]
            nums = lambda field: [int(row[field]) for row in rows]
            writer.writerow({
                "family": key[0], "row_count": key[1], "conflict_ratio": key[2],
                "algorithm": key[3], "n": len(rows),
                "median_decision_ns": int(statistics.median(nums("decision_ns"))),
                "p95_decision_ns": int(_percentile(nums("decision_ns"), .95)),
                "median_build_ns": int(statistics.median(nums("build_ns"))),
                "median_check_ns": int(statistics.median(nums("check_ns"))),
                "median_diagnose_ns": int(statistics.median(nums("diagnose_ns"))),
                "median_incremental_remove_ns": int(statistics.median(nums("incremental_remove_ns"))),
                "median_incremental_add_ns": int(statistics.median(nums("incremental_add_ns"))),
                "max_peak_bytes": max(nums("peak_bytes")),
                "agreement_rate": sum(row["is_repair"] == "True" and row["candidate_consistent"] == "True" for row in rows) / len(rows),
            })


def write_report_and_figure(summary_path: Path, report_path: Path, figure_path: Path):
    with summary_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("empty benchmark summary")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    figure_path.parent.mkdir(parents=True, exist_ok=True)
    by_cell = defaultdict(dict)
    by_algorithm = defaultdict(list)
    for row in rows:
        key = (row["family"], int(row["row_count"]), float(row["conflict_ratio"]))
        latency = int(row["median_decision_ns"])
        by_cell[key][row["algorithm"]] = latency
        by_algorithm[row["algorithm"]].append(latency)
    speedups = defaultdict(list)
    for cell in by_cell.values():
        base = cell.get("bcnf_index")
        if not base:
            continue
        for name, latency in cell.items():
            if name != "bcnf_index" and latency > 0:
                speedups[name].append(latency / base)
    min_agreement = min(float(row["agreement_rate"]) for row in rows)
    lines = [
        "# BCNF结构与效率微基准",
        "",
        "本实验在同机单进程环境中比较 BCNF 专用索引、通用 FD 哈希、工程通用后端、增量状态和单例全扫描。候选集合均为包含极大修复，数据生成不计入算法计时。",
        "",
        "## 验证结论",
        "",
        f"- 所有已执行后端与独立通用判定的一致率下界为 {min_agreement:.0%}。",
        f"- 最大测试规模为 {max(int(row['row_count']) for row in rows):,} 行。",
        "- 计时使用 `time.perf_counter_ns()`；每格先构造固定实例，再独立计量。",
        "- 全扫描在资源上限以外明确记为 `SKIPPED_RESOURCE_CAP`，不伪造或外推其观测时间。",
        "",
        "## 汇总",
        "",
        "| 后端 | 跨场景决策延迟中位数 ms | 相对 BCNF 索引的中位倍率 |",
        "|---|---:|---:|",
    ]
    display = {
        "bcnf_index": "BCNF-Index", "fd_hash": "FD-Hash",
        "repair_agent_generic": "Generic", "incremental": "Incremental init",
        "singleton_fullscan": "Singleton-FullScan",
    }
    for name in sorted(by_algorithm):
        median_ms = statistics.median(by_algorithm[name]) / 1e6
        ratio = 1.0 if name == "bcnf_index" else statistics.median(speedups.get(name, [0]))
        lines.append(f"| {display.get(name, name)} | {median_ms:.4f} | {ratio:.2f}x |")
    lines += [
        "",
        "## 论文使用边界",
        "",
        "该微基准支持 BCNF 专用结构在判定等价前提下的工程效率比较，不支持把合成计时直接外推到任意真实数据库负载。全扫描缺失的大规模格子属于预注册资源上限，不应填补为估算值。",
        "",
        f"原始汇总：`{summary_path.as_posix()}`",
    ]
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    points = defaultdict(lambda: defaultdict(list))
    for row in rows:
        points[row["algorithm"]][int(row["row_count"])].append(int(row["median_decision_ns"]) / 1e6)
    width, height = 960, 560
    left, right, top, bottom = 90, 35, 45, 75
    plot_w, plot_h = width - left - right, height - top - bottom
    xs = sorted({size for series in points.values() for size in series})
    ys = [value for series in points.values() for values in series.values() for value in values if value > 0]
    x0, x1 = math.log10(min(xs)), math.log10(max(xs))
    y0, y1 = math.log10(min(ys)), math.log10(max(ys))
    if x0 == x1: x1 = x0 + 1
    if y0 == y1: y1 = y0 + 1
    xcoord = lambda value: left + (math.log10(value) - x0) / (x1 - x0) * plot_w
    ycoord = lambda value: top + (y1 - math.log10(value)) / (y1 - y0) * plot_h
    colors = {"bcnf_index": "#1f4e79", "fd_hash": "#2e75b6",
              "repair_agent_generic": "#70ad47", "incremental": "#ed7d31",
              "singleton_fullscan": "#a5a5a5"}
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
           '<rect width="100%" height="100%" fill="white"/>',
           '<text x="480" y="26" text-anchor="middle" font-family="Arial" font-size="18" font-weight="bold">BCNF backend scaling</text>',
           f'<line x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}" stroke="#444"/>',
           f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#444"/>']
    for size in xs:
        x = xcoord(size)
        svg += [f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top + plot_h}" stroke="#e6e6e6"/>',
                f'<text x="{x:.1f}" y="{top + plot_h + 24}" text-anchor="middle" font-family="Arial" font-size="12">{size:,}</text>']
    for exponent in range(math.floor(y0), math.ceil(y1) + 1):
        value = 10 ** exponent
        y = ycoord(value)
        svg += [f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" stroke="#e6e6e6"/>',
                f'<text x="{left - 10}" y="{y + 4:.1f}" text-anchor="end" font-family="Arial" font-size="12">{value:g}</text>']
    for index, name in enumerate(sorted(points)):
        series = []
        for size in sorted(points[name]):
            series.append((xcoord(size), ycoord(statistics.median(points[name][size]))))
        color = colors.get(name, "#000")
        svg.append(f'<polyline fill="none" stroke="{color}" stroke-width="2.5" points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in series) + '"/>')
        for x, y in series:
            svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{color}"/>')
        ly = top + 18 + index * 20
        svg += [f'<line x1="{left + 15}" y1="{ly}" x2="{left + 42}" y2="{ly}" stroke="{color}" stroke-width="3"/>',
                f'<text x="{left + 50}" y="{ly + 4}" font-family="Arial" font-size="12">{display.get(name, name)}</text>']
    svg += [f'<text x="{left + plot_w/2}" y="{height - 22}" text-anchor="middle" font-family="Arial" font-size="13">Rows (log scale)</text>',
            f'<text x="20" y="{top + plot_h/2}" transform="rotate(-90 20 {top + plot_h/2})" text-anchor="middle" font-family="Arial" font-size="13">Median decision latency ms (log scale)</text>',
            '</svg>']
    figure_path.write_text("\n".join(svg) + "\n", encoding="utf-8")


def run_matrix(output_dir: Path, row_counts, families, conflict_ratios, seeds,
               repetitions: int, fullscan_max_rows: int):
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / "bcnf_backend_raw.csv"
    summary_path = output_dir / "bcnf_backend_summary.csv"
    metadata_path = output_dir / "environment.json"
    metadata_path.write_text(json.dumps({
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "python": sys.version, "platform": platform.platform(),
        "processor": platform.processor(), "logical_cpu_count": os.cpu_count(),
        "timer": "time.perf_counter_ns", "process_model": "single process",
        "fullscan_max_rows": fullscan_max_rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    existing = set()
    if raw_path.exists():
        with raw_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                existing.add((row["family"], int(row["row_count"]), float(row["conflict_ratio"]),
                              int(row["seed"]), row["algorithm"], int(row["repeat"])))
    needs_header = not raw_path.exists() or raw_path.stat().st_size == 0
    algorithms = ("bcnf_index", "fd_hash", "repair_agent_generic", "incremental", "singleton_fullscan")
    with raw_path.open("a", encoding="utf-8", newline="", buffering=1) as handle:
        writer = csv.DictWriter(handle, fieldnames=RAW_FIELDS)
        if needs_header:
            writer.writeheader()
        for row_count in row_counts:
            for family in families:
                for ratio in conflict_ratios:
                    for seed in seeds:
                        schema, rows, retained = build_instance(row_count, family, ratio, seed)
                        reference = check_all_backends(schema, rows, retained, include_fullscan=row_count <= fullscan_max_rows)
                        if len({(value.is_repair, value.candidate_consistent) for value in reference.values()}) != 1:
                            raise RuntimeError("backend disagreement before timing")
                        for name in algorithms:
                            for repeat in range(repetitions):
                                key = (family, row_count, float(ratio), seed, name, repeat)
                                if key in existing:
                                    continue
                                base = {"family": family, "row_count": row_count,
                                        "conflict_ratio": ratio, "seed": seed,
                                        "algorithm": name, "repeat": repeat}
                                if name == "singleton_fullscan" and row_count > fullscan_max_rows:
                                    row = {**base, "status": "SKIPPED_RESOURCE_CAP",
                                           "is_repair": "", "candidate_consistent": "",
                                           "decision_ns": 0, "build_ns": 0, "check_ns": 0,
                                           "diagnose_ns": 0, "incremental_remove_ns": 0,
                                           "incremental_add_ns": 0, "peak_bytes": 0, "index_count": 0}
                                else:
                                    try:
                                        row = {**base, **_bench_algorithm(name, schema, rows, retained, repeat)}
                                    except Exception as exc:
                                        row = {**base, "status": f"ERROR:{type(exc).__name__}",
                                               "is_repair": "", "candidate_consistent": "",
                                               "decision_ns": 0, "build_ns": 0, "check_ns": 0,
                                               "diagnose_ns": 0, "incremental_remove_ns": 0,
                                               "incremental_add_ns": 0, "peak_bytes": 0, "index_count": 0}
                                writer.writerow(row)
                                handle.flush()
    _write_summary(raw_path, summary_path)
    return raw_path, summary_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--rows", default="1000,5000,10000,50000")
    parser.add_argument("--families", default="single,dual,composite")
    parser.add_argument("--ratios", default="0,0.01,0.05,0.15")
    parser.add_argument("--seeds", default="1,2,3,4,5")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--fullscan-max-rows", type=int, default=5000)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--figure", type=Path)
    args = parser.parse_args()
    raw, summary = run_matrix(
        args.out,
        [int(x) for x in args.rows.split(",")],
        args.families.split(","),
        [float(x) for x in args.ratios.split(",")],
        [int(x) for x in args.seeds.split(",")],
        args.repetitions,
        args.fullscan_max_rows,
    )
    if args.report and args.figure:
        write_report_and_figure(summary, args.report, args.figure)
    print(json.dumps({"raw": str(raw), "summary": str(summary)}, ensure_ascii=False))


if __name__ == "__main__":
    main()

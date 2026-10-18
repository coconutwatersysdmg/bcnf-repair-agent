"""FD-Hash: general FD hash-index baseline (no BCNF key compression)."""

from __future__ import annotations

import time
from typing import Any, Sequence

from common.fd_utils import nontrivial_fds, project_row
from common.types import FD, RelationSchema, RepairCheckResult, Row, ensure_subset


def _build_fd_indexes(
    r_prime: Sequence[Row],
    fds: Sequence[FD],
    attr_to_idx: dict[str, int],
) -> tuple[dict[FD, dict[tuple[Any, ...], tuple[Any, ...]]], bool]:
    """Build X-value -> Y-value maps for each nontrivial FD.

    Returns (indexes, consistent).
    """
    indexes: dict[FD, dict[tuple[Any, ...], tuple[Any, ...]]] = {}
    for fd in fds:
        idx: dict[tuple[Any, ...], tuple[Any, ...]] = {}
        for row in r_prime:
            x = project_row(row, fd.lhs, attr_to_idx)
            y = project_row(row, fd.rhs, attr_to_idx)
            prev = idx.get(x)
            if prev is None:
                idx[x] = y
            elif prev != y:
                return {}, False
        indexes[fd] = idx
    return indexes, True


def is_subset_repair_fd_hash(
    schema: RelationSchema,
    r: Sequence[Row],
    r_prime: Sequence[Row],
) -> RepairCheckResult:
    """Check S-repair using per-FD hash indexes on r_prime (general FD, not BCNF).

    Timing matches BCNF-Index:
      validation_time / build_time / check_time / total_time
    Pure decision baseline: no certificates.
    """
    t0 = time.perf_counter()

    t_val0 = time.perf_counter()
    ensure_subset(r, r_prime)
    validation_t = time.perf_counter() - t_val0

    attr_to_idx = schema.attr_to_idx
    fds = nontrivial_fds(schema.fds)

    t_build0 = time.perf_counter()
    indexes, consistent = _build_fd_indexes(r_prime, fds, attr_to_idx)
    build_t = time.perf_counter() - t_build0

    base_meta = {
        "algorithm": "FD-Hash",
        "validation_time_sec": validation_t,
    }

    if not consistent:
        total = time.perf_counter() - t0
        return RepairCheckResult(
            is_repair=False,
            candidate_consistent=False,
            build_time_sec=build_t,
            check_time_sec=0.0,
            total_time_sec=total,
            index_count=len(fds),
            metadata={**base_meta, "reason": "r_prime_inconsistent"},
        )

    t_check0 = time.perf_counter()
    r_prime_set = set(r_prime)
    deleted_count = 0
    for t in r:
        if t in r_prime_set:
            continue
        deleted_count += 1
        conflict = False
        for fd in fds:
            x = project_row(t, fd.lhs, attr_to_idx)
            y = project_row(t, fd.rhs, attr_to_idx)
            prev_y = indexes[fd].get(x)
            if prev_y is not None and prev_y != y:
                conflict = True
                break
        if not conflict:
            check_t = time.perf_counter() - t_check0
            total = time.perf_counter() - t0
            return RepairCheckResult(
                is_repair=False,
                candidate_consistent=True,
                addable_tuple=t,
                witness_addable_subset=(t,),
                build_time_sec=build_t,
                check_time_sec=check_t,
                total_time_sec=total,
                index_count=len(fds),
                metadata={**base_meta, "deleted_count": deleted_count},
            )

    check_t = time.perf_counter() - t_check0
    total = time.perf_counter() - t0
    return RepairCheckResult(
        is_repair=True,
        candidate_consistent=True,
        build_time_sec=build_t,
        check_time_sec=check_t,
        total_time_sec=total,
        index_count=len(fds),
        metadata={**base_meta, "deleted_count": deleted_count},
    )

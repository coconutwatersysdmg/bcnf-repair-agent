"""Definition-level exhaustive oracle for subset-repair checking.

This module is NOT a scalable baseline. It enumerates all non-empty subsets
of deleted tuples and is intended only for small correctness oracles.
"""

from __future__ import annotations

import itertools
import time
from typing import Optional, Sequence

from common.fd_utils import satisfies_fds
from common.types import RelationSchema, RepairCheckResult, Row, ensure_subset


class DeletedTooLargeError(ValueError):
    """Raised when |D| exceeds the exhaustive oracle budget."""


def is_subset_repair_exhaustive(
    schema: RelationSchema,
    r: Sequence[Row],
    r_prime: Sequence[Row],
    max_deleted: int = 15,
) -> RepairCheckResult:
    """Exact subset-repair check by enumerating all non-empty subsets of D.

    Steps:
      1. Verify r' ⊆ r
      2. Verify r' satisfies F
      3. D = r \\ r'
      4. If |D| > max_deleted, raise DeletedTooLargeError
      5. Enumerate all non-empty A ⊆ D
      6. If any r' ∪ A satisfies F, return False (with witness A)
      7. Otherwise return True

    Do not use for 10^5 / 10^6 scales.
    """
    t0 = time.perf_counter()
    ensure_subset(r, r_prime)
    attr_to_idx = schema.attr_to_idx
    fds = schema.fds

    if not satisfies_fds(r_prime, fds, attr_to_idx):
        total = time.perf_counter() - t0
        return RepairCheckResult(
            is_repair=False,
            candidate_consistent=False,
            check_time_sec=total,
            total_time_sec=total,
            metadata={"algorithm": "Exhaustive", "reason": "r_prime_inconsistent"},
        )

    d = list(frozenset(r) - frozenset(r_prime))
    if len(d) > max_deleted:
        raise DeletedTooLargeError(
            f"|D|={len(d)} exceeds max_deleted={max_deleted} for exhaustive oracle"
        )

    r_prime_set = set(r_prime)
    t_check0 = time.perf_counter()
    for k in range(1, len(d) + 1):
        for A in itertools.combinations(d, k):
            candidate = list(r_prime_set)
            candidate.extend(A)
            if satisfies_fds(candidate, fds, attr_to_idx):
                check_t = time.perf_counter() - t_check0
                total = time.perf_counter() - t0
                return RepairCheckResult(
                    is_repair=False,
                    candidate_consistent=True,
                    addable_tuple=A[0] if len(A) == 1 else None,
                    witness_addable_subset=tuple(A),
                    check_time_sec=check_t,
                    total_time_sec=total,
                    metadata={"algorithm": "Exhaustive", "witness_size": len(A)},
                )

    check_t = time.perf_counter() - t_check0
    total = time.perf_counter() - t0
    return RepairCheckResult(
        is_repair=True,
        candidate_consistent=True,
        check_time_sec=check_t,
        total_time_sec=total,
        metadata={"algorithm": "Exhaustive", "deleted_count": len(d)},
    )

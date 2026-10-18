"""BCNF-Index: formal static BCNF subset-repair checker."""

from __future__ import annotations

import time
from typing import Any, Optional, Sequence

from common.fd_utils import minimize_superkey, nontrivial_fds, project_row
from common.types import FD, RelationSchema, RepairCheckResult, Row, ensure_subset


def compute_candidate_keys_from_fds(
    schema: RelationSchema,
) -> list[frozenset[str]]:
    """For each nontrivial FD X->Y, compute K = minimize_superkey(X,U,F); dedup."""
    keys: list[frozenset[str]] = []
    seen: set[frozenset[str]] = set()
    for fd in nontrivial_fds(schema.fds):
        k = minimize_superkey(fd.lhs, schema.attributes, schema.fds)
        if k not in seen:
            seen.add(k)
            keys.append(k)
    return keys


def greedy_key_cover(
    schema: RelationSchema,
    candidate_keys: Sequence[frozenset[str]],
) -> list[frozenset[str]]:
    """Greedy set-cover over nontrivial FDs using candidate keys.

    Cover(K) = all nontrivial FDs with K ⊆ X.
    Only keys satisfying K ⊆ X may cover an FD X->Y.

    Optional experimental optimization; not part of the paper's main algorithm.
    """
    fds = list(nontrivial_fds(schema.fds))
    if not fds:
        return []

    uncovered = set(range(len(fds)))
    remaining_keys = list(candidate_keys)
    chosen: list[frozenset[str]] = []

    def covers(k: frozenset[str], fd: FD) -> bool:
        return k <= fd.lhs_set

    while uncovered:
        best_k: Optional[frozenset[str]] = None
        best_cover: set[int] = set()
        for k in remaining_keys:
            c = {i for i in uncovered if covers(k, fds[i])}
            if len(c) > len(best_cover):
                best_cover = c
                best_k = k
        if best_k is None or not best_cover:
            # Safety: if greedy fails (should not for valid BCNF schemas with
            # keys derived from FD LHSs), fall back to all remaining keys.
            for k in remaining_keys:
                if k not in chosen:
                    chosen.append(k)
            break
        chosen.append(best_k)
        remaining_keys = [k for k in remaining_keys if k != best_k]
        uncovered -= best_cover
    return chosen


def _key_as_ordered_tuple(
    k: frozenset[str],
    schema: RelationSchema,
) -> tuple[str, ...]:
    """Order key attributes by schema.attributes natural order (not lexicographic)."""
    order = {attr: i for i, attr in enumerate(schema.attributes)}
    return tuple(sorted(k, key=lambda a: order[a]))


def select_index_keys(
    schema: RelationSchema,
    use_key_cover: bool = False,
) -> list[tuple[str, ...]]:
    """Return ordered index keys as stable tuples (schema attribute order)."""
    cand = compute_candidate_keys_from_fds(schema)
    if use_key_cover:
        keys = greedy_key_cover(schema, cand)
    else:
        keys = cand
    return [_key_as_ordered_tuple(k, schema) for k in keys]


class BCNFRepairChecker:
    """Static BCNF subset-repair checker with candidate-key indexes.

    Raises ValueError at init if schema is not BCNF.
    Paper main algorithm: minimize superkey → candidate keys → identical-key
    dedup → build indexes. Greedy key-cover is optional (use_key_cover=False).
    """

    def __init__(
        self,
        schema: RelationSchema,
        use_key_cover: bool = False,
    ) -> None:
        schema.validate()
        schema.validate_bcnf()
        self.schema = schema
        self.use_key_cover = use_key_cover
        self.index_keys: list[tuple[str, ...]] = select_index_keys(schema, use_key_cover)
        self.attr_to_idx = schema.attr_to_idx
        self._indexes: dict[tuple[str, ...], dict[tuple[Any, ...], Row]] = {}
        self._build_time = 0.0
        self._consistent = True

    @property
    def index_count(self) -> int:
        return len(self.index_keys)

    def build(self, r_prime: Sequence[Row]) -> bool:
        """Build H[K][key_value] = retained_row. Return False if r' inconsistent."""
        t0 = time.perf_counter()
        indexes: dict[tuple[str, ...], dict[tuple[Any, ...], Row]] = {}
        for k in self.index_keys:
            h: dict[tuple[Any, ...], Row] = {}
            for row in r_prime:
                kv = project_row(row, k, self.attr_to_idx)
                prev = h.get(kv)
                if prev is not None and prev != row:
                    self._indexes = {}
                    self._consistent = False
                    self._build_time = time.perf_counter() - t0
                    return False
                h[kv] = row
            indexes[k] = h
        self._indexes = indexes
        self._consistent = True
        self._build_time = time.perf_counter() - t0
        return True

    def find_conflict_witness(self, t: Row) -> Optional[dict[str, Any]]:
        """On-demand conflict explanation for a single deleted tuple t.

        Requires indexes already built (via build() or a prior check()).
        Returns None if t is not blocked by current r'.
        """
        if not self._consistent or not self._indexes:
            return None
        for k in self.index_keys:
            kv = project_row(t, k, self.attr_to_idx)
            s = self._indexes[k].get(kv)
            if s is not None:
                return {
                    "key": k,
                    "key_value": kv,
                    "retained_row": s,
                    "deleted_row": t,
                }
        return None

    def check(
        self,
        r: Sequence[Row],
        r_prime: Sequence[Row],
        already_built: bool = False,
        collect_certificates: bool = False,
    ) -> RepairCheckResult:
        """Check whether r' is an S-repair of r w.r.t. F under BCNF.

        Timing:
          validation_time: ensure_subset / input validation
          build_time: index construction
          check_time: from r_prime_set construction through deleted scans
          total_time: entire public check call
        """
        t0 = time.perf_counter()

        t_val0 = time.perf_counter()
        ensure_subset(r, r_prime)
        validation_t = time.perf_counter() - t_val0

        if not already_built:
            ok = self.build(r_prime)
        else:
            ok = self._consistent

        build_t = self._build_time
        base_meta = {
            "algorithm": "BCNF-Index",
            "use_key_cover": self.use_key_cover,
            "validation_time_sec": validation_t,
            "collect_certificates": collect_certificates,
        }

        if not ok:
            total = time.perf_counter() - t0
            return RepairCheckResult(
                is_repair=False,
                candidate_consistent=False,
                build_time_sec=build_t,
                check_time_sec=0.0,
                total_time_sec=total,
                index_count=self.index_count,
                metadata={**base_meta, "reason": "r_prime_inconsistent"},
            )

        certificate: dict[Any, Any] = {} if collect_certificates else {}
        t_check0 = time.perf_counter()
        r_prime_set = set(r_prime)
        deleted_count = 0

        for t in r:
            if t in r_prime_set:
                continue
            deleted_count += 1
            blocked = False
            for k in self.index_keys:
                kv = project_row(t, k, self.attr_to_idx)
                s = self._indexes[k].get(kv)
                if s is not None:
                    blocked = True
                    # Certificate explains why t cannot rejoin current r'.
                    # It does NOT claim t is "erroneous" or s is "true".
                    if collect_certificates:
                        certificate[t] = {
                            "key": k,
                            "key_value": kv,
                            "retained_row": s,
                            "deleted_row": t,
                        }
                    break
            if not blocked:
                check_t = time.perf_counter() - t_check0
                total = time.perf_counter() - t0
                return RepairCheckResult(
                    is_repair=False,
                    candidate_consistent=True,
                    addable_tuple=t,
                    witness_addable_subset=(t,),
                    certificate=certificate,
                    build_time_sec=build_t,
                    check_time_sec=check_t,
                    total_time_sec=total,
                    index_count=self.index_count,
                    metadata={**base_meta, "deleted_count": deleted_count},
                )

        check_t = time.perf_counter() - t_check0
        total = time.perf_counter() - t0
        return RepairCheckResult(
            is_repair=True,
            candidate_consistent=True,
            certificate=certificate,
            build_time_sec=build_t,
            check_time_sec=check_t,
            total_time_sec=total,
            index_count=self.index_count,
            metadata={**base_meta, "deleted_count": deleted_count},
        )


def is_subset_repair_bcnf_index(
    schema: RelationSchema,
    r: Sequence[Row],
    r_prime: Sequence[Row],
    use_key_cover: bool = False,
    collect_certificates: bool = False,
) -> RepairCheckResult:
    """Convenience wrapper around BCNFRepairChecker (paper defaults)."""
    checker = BCNFRepairChecker(schema, use_key_cover=use_key_cover)
    return checker.check(r, r_prime, collect_certificates=collect_certificates)

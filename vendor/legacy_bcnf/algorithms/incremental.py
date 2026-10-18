"""Incremental BCNF repair state with differential updates."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from algorithms.bcnf_index import BCNFRepairChecker, select_index_keys
from common.fd_utils import project_row
from common.types import RelationSchema, Row


@dataclass(frozen=True)
class UpdateOp:
    """Precomputed update; workload generation is outside algorithm timers."""

    kind: str
    row: Row
    aux_row: Optional[Row] = None


class PlainRepairState:
    """Lightweight set-only state for static-rebuild baseline replay."""

    def __init__(self, r: Sequence[Row], r_prime: Sequence[Row]) -> None:
        self.r: set[Row] = set(r)
        self.r_prime: set[Row] = set(r_prime)
        if not self.r_prime <= self.r:
            raise ValueError("r_prime must be subset of r")
        self.D: set[Row] = self.r - self.r_prime

    def apply(self, op: UpdateOp) -> None:
        if op.kind == "add_deleted":
            if op.row in self.r:
                raise ValueError("tuple already in r")
            self.r.add(op.row)
            self.D.add(op.row)
        elif op.kind == "remove_deleted":
            if op.row not in self.D:
                raise ValueError("tuple not in D")
            self.D.remove(op.row)
            self.r.remove(op.row)
        elif op.kind == "move_deleted_to_retained":
            if op.row not in self.D:
                raise ValueError("tuple not in D")
            self.D.remove(op.row)
            self.r_prime.add(op.row)
        elif op.kind == "move_retained_to_deleted":
            if op.row not in self.r_prime:
                raise ValueError("tuple not in r_prime")
            self.r_prime.remove(op.row)
            self.D.add(op.row)
        elif op.kind == "swap":
            # Logical swap: retained s <-> deleted t (aux_row = deleted)
            s = op.row
            t = op.aux_row
            if t is None:
                raise ValueError("swap requires aux_row")
            if s not in self.r_prime or t not in self.D:
                raise ValueError("swap operands not in expected partitions")
            self.r_prime.remove(s)
            self.D.add(s)
            self.D.remove(t)
            self.r_prime.add(t)
        else:
            raise ValueError(f"unknown UpdateOp.kind: {op.kind}")

    def apply_batch(self, ops: Sequence[UpdateOp]) -> None:
        for op in ops:
            self.apply(op)


class BCNFRepairState:
    """Maintain S-repair status under local updates to r / r'.

    State invariants (see paper / experiment protocol):
      - C[K][v]: retained count for key value v under index key K
      - G[K][v]: deleted rows with projection K = v
      - b[t]: number of index keys blocking deleted tuple t
      - unblocked_count: |{t in D : b[t] == 0}|
      - bad_block_count: number of (K,v) with C[K][v] >= 2
      - is_repair <=> bad_block_count == 0 and unblocked_count == 0
    """

    def __init__(
        self,
        schema: RelationSchema,
        r: Sequence[Row],
        r_prime: Sequence[Row],
        index_keys: Optional[Sequence[tuple[str, ...]]] = None,
        use_key_cover: bool = False,
    ) -> None:
        schema.validate_bcnf()
        self.schema = schema
        self.attr_to_idx = schema.attr_to_idx
        self.index_keys: list[tuple[str, ...]] = (
            list(index_keys)
            if index_keys is not None
            else select_index_keys(schema, use_key_cover)
        )
        self.use_key_cover = use_key_cover

        self.r: set[Row] = set(r)
        self.r_prime: set[Row] = set(r_prime)
        if not self.r_prime <= self.r:
            raise ValueError("r_prime must be subset of r")

        self.D: set[Row] = self.r - self.r_prime

        # C[K][v] retained counts
        self.C: dict[tuple[str, ...], dict[tuple[Any, ...], int]] = {
            k: defaultdict(int) for k in self.index_keys
        }
        # G[K][v] deleted inverted index
        self.G: dict[tuple[str, ...], dict[tuple[Any, ...], set[Row]]] = {
            k: defaultdict(set) for k in self.index_keys
        }
        self.b: dict[Row, int] = {}
        self.bad_block_count = 0
        self.unblocked_count = 0

        # Real incremental work counters (Σ |G_K(v)| over scanned blocks)
        self.touched_block_entries = 0
        self.touched_block_count = 0
        self.projection_count = 0

        self._rebuild_from_scratch()

    def reset_work_counters(self) -> None:
        self.touched_block_entries = 0
        self.touched_block_count = 0
        self.projection_count = 0

    def _kv(self, row: Row, k: tuple[str, ...]) -> tuple[Any, ...]:
        self.projection_count += 1
        return project_row(row, k, self.attr_to_idx)

    def _rebuild_from_scratch(self) -> None:
        for k in self.index_keys:
            self.C[k].clear()
            self.G[k].clear()
        self.b.clear()
        self.bad_block_count = 0
        self.unblocked_count = 0

        for row in self.r_prime:
            for k in self.index_keys:
                v = self._kv(row, k)
                prev = self.C[k][v]
                self.C[k][v] = prev + 1
                if prev == 1:
                    self.bad_block_count += 1

        for t in self.D:
            bt = 0
            for k in self.index_keys:
                v = self._kv(t, k)
                self.G[k][v].add(t)
                # Read-only query: never create zero entries via defaultdict
                if self.C[k].get(v, 0) > 0:
                    bt += 1
            self.b[t] = bt
            if bt == 0:
                self.unblocked_count += 1

    def is_repair(self) -> bool:
        return self.bad_block_count == 0 and self.unblocked_count == 0

    def candidate_consistent(self) -> bool:
        return self.bad_block_count == 0

    def add_deleted(self, t: Row) -> None:
        """New tuple joins r and belongs to D (not r_prime)."""
        if t in self.r:
            raise ValueError("tuple already in r")
        self.r.add(t)
        self.D.add(t)
        bt = 0
        for k in self.index_keys:
            v = self._kv(t, k)
            self.G[k][v].add(t)
            if self.C[k].get(v, 0) > 0:
                bt += 1
        self.b[t] = bt
        if bt == 0:
            self.unblocked_count += 1

    def remove_deleted(self, t: Row) -> None:
        """Remove tuple from r entirely; it must currently be in D."""
        if t not in self.D:
            raise ValueError("tuple not in D")
        bt = self.b.pop(t)
        if bt == 0:
            self.unblocked_count -= 1
        for k in self.index_keys:
            v = self._kv(t, k)
            group = self.G[k].get(v)
            if group is None:
                continue
            group.discard(t)
            if not group:
                del self.G[k][v]
        self.D.remove(t)
        self.r.remove(t)

    def move_deleted_to_retained(self, t: Row) -> None:
        """t was in D; now join r_prime (still in r)."""
        if t not in self.D:
            raise ValueError("tuple not in D")

        # 1. Remove t from D/G/b first
        bt = self.b.pop(t)
        if bt == 0:
            self.unblocked_count -= 1
        for k in self.index_keys:
            v = self._kv(t, k)
            group = self.G[k].get(v)
            if group is not None:
                group.discard(t)
                if not group:
                    del self.G[k][v]
        self.D.remove(t)

        # 2-4. Increase retained counts
        for k in self.index_keys:
            v = self._kv(t, k)
            prev = self.C[k][v]
            self.C[k][v] = prev + 1
            if prev == 0:
                # 0 -> 1: newly blocks deleted rows with this key value
                group = self.G[k].get(v, ())
                self.touched_block_count += 1
                self.touched_block_entries += len(group)
                for x in group:
                    old = self.b[x]
                    self.b[x] = old + 1
                    if old == 0:
                        self.unblocked_count -= 1
            elif prev == 1:
                # 1 -> 2
                self.bad_block_count += 1

        self.r_prime.add(t)

    def move_retained_to_deleted(self, t: Row) -> None:
        """t was in r_prime; move to D."""
        if t not in self.r_prime:
            raise ValueError("tuple not in r_prime")

        # 1-4. Decrease retained counts first
        for k in self.index_keys:
            v = self._kv(t, k)
            prev = self.C[k].get(v, 0)
            if prev <= 0:
                raise RuntimeError("inconsistent retained count")
            self.C[k][v] = prev - 1
            if prev == 2:
                self.bad_block_count -= 1
            elif prev == 1:
                # 1 -> 0: unblock deleted rows with this key value
                group = self.G[k].get(v, ())
                self.touched_block_count += 1
                self.touched_block_entries += len(group)
                for x in group:
                    old = self.b[x]
                    self.b[x] = old - 1
                    if old == 1:
                        self.unblocked_count += 1
                if self.C[k][v] == 0:
                    del self.C[k][v]

        self.r_prime.remove(t)

        # 5-7. Add t to D/G and compute b[t]
        self.D.add(t)
        bt = 0
        for k in self.index_keys:
            v = self._kv(t, k)
            self.G[k][v].add(t)
            if self.C[k].get(v, 0) > 0:
                bt += 1
        self.b[t] = bt
        if bt == 0:
            self.unblocked_count += 1

    def apply(self, op: UpdateOp) -> None:
        """Apply a precomputed UpdateOp (same semantics as PlainRepairState)."""
        if op.kind == "add_deleted":
            self.add_deleted(op.row)
        elif op.kind == "remove_deleted":
            self.remove_deleted(op.row)
        elif op.kind == "move_deleted_to_retained":
            self.move_deleted_to_retained(op.row)
        elif op.kind == "move_retained_to_deleted":
            self.move_retained_to_deleted(op.row)
        elif op.kind == "swap":
            s = op.row
            t = op.aux_row
            if t is None:
                raise ValueError("swap requires aux_row")
            self.move_retained_to_deleted(s)
            self.move_deleted_to_retained(t)
        else:
            raise ValueError(f"unknown UpdateOp.kind: {op.kind}")

    def apply_batch(self, ops: Sequence[UpdateOp]) -> None:
        for op in ops:
            self.apply(op)

    def validate_against_static(self) -> bool:
        """Recompute with BCNFRepairChecker; return True iff results match."""
        static = BCNFRepairChecker(self.schema, use_key_cover=False)
        # Align index keys with this state when possible
        static.index_keys = list(self.index_keys)
        result = static.check(
            list(self.r),
            list(self.r_prime),
            collect_certificates=False,
        )
        inc_repair = self.is_repair()
        # If candidate inconsistent, static says is_repair=False and candidate_consistent=False
        if not self.candidate_consistent():
            return (not result.is_repair) and (not result.candidate_consistent) and (not inc_repair)
        return result.is_repair == inc_repair and result.candidate_consistent == self.candidate_consistent()

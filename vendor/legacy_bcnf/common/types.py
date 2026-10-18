"""Shared type definitions for subset-repair experiments."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping, Optional, Sequence


@dataclass(frozen=True)
class FD:
    """A functional dependency X -> Y.

    Attribute order inside lhs/rhs is stable; duplicates are not allowed.
    """

    lhs: tuple[str, ...]
    rhs: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.lhs) != len(set(self.lhs)):
            raise ValueError(f"FD lhs has duplicate attributes: {self.lhs}")
        if len(self.rhs) != len(set(self.rhs)):
            raise ValueError(f"FD rhs has duplicate attributes: {self.rhs}")

    @property
    def lhs_set(self) -> frozenset[str]:
        return frozenset(self.lhs)

    @property
    def rhs_set(self) -> frozenset[str]:
        return frozenset(self.rhs)

    def is_trivial(self) -> bool:
        """Return True iff rhs ⊆ lhs."""
        return self.rhs_set <= self.lhs_set

    def to_json(self) -> dict[str, Any]:
        return {"lhs": list(self.lhs), "rhs": list(self.rhs)}

    @classmethod
    def from_json(cls, obj: Mapping[str, Any]) -> "FD":
        return cls(lhs=tuple(obj["lhs"]), rhs=tuple(obj["rhs"]))

    def __str__(self) -> str:
        return f"{','.join(self.lhs)}->{','.join(self.rhs)}"


Row = tuple[Any, ...]


@dataclass(frozen=True)
class RelationSchema:
    """Relation schema R(U, F)."""

    attributes: tuple[str, ...]
    fds: tuple[FD, ...]
    candidate_keys: tuple[tuple[str, ...], ...] = ()
    name: str = "R"

    def __post_init__(self) -> None:
        if len(self.attributes) != len(set(self.attributes)):
            raise ValueError(f"Duplicate attributes in U: {self.attributes}")
        known = set(self.attributes)
        for fd in self.fds:
            if not fd.lhs_set <= known:
                raise ValueError(f"FD {fd} lhs not in U={self.attributes}")
            if not fd.rhs_set <= known:
                raise ValueError(f"FD {fd} rhs not in U={self.attributes}")

    @property
    def U(self) -> frozenset[str]:
        return frozenset(self.attributes)

    @property
    def attr_to_idx(self) -> dict[str, int]:
        return {a: i for i, a in enumerate(self.attributes)}

    def validate(self) -> None:
        """Validate structural well-formedness of R(U, F)."""
        # Construction already checks attribute/FD consistency.
        if not self.attributes:
            raise ValueError("Schema attributes U must be non-empty")

    def validate_bcnf(self) -> bool:
        """Validate that R(U, F) is in BCNF; raise ValueError if not."""
        from common.fd_utils import validate_bcnf

        ok = validate_bcnf(self.U, self.fds)
        if not ok:
            raise ValueError(
                f"Schema {self.name} R(U,F) is not in BCNF; "
                "BCNF experiments must not continue."
            )
        return True

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "attributes": list(self.attributes),
            "fds": [fd.to_json() for fd in self.fds],
            "candidate_keys": [list(k) for k in self.candidate_keys],
        }

    @classmethod
    def from_json(cls, obj: Mapping[str, Any]) -> "RelationSchema":
        return cls(
            attributes=tuple(obj["attributes"]),
            fds=tuple(FD.from_json(fd) for fd in obj["fds"]),
            candidate_keys=tuple(tuple(k) for k in obj.get("candidate_keys", [])),
            name=str(obj.get("name", "R")),
        )


@dataclass
class RepairInstance:
    """A candidate subset-repair check instance (r, r')."""

    schema: RelationSchema
    r: tuple[Row, ...]
    r_prime: tuple[Row, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        r_set = set(self.r)
        if len(r_set) != len(self.r):
            raise ValueError("Instance r must use set semantics (no duplicate tuples)")
        rp_set = set(self.r_prime)
        if len(rp_set) != len(self.r_prime):
            raise ValueError("r_prime must use set semantics (no duplicate tuples)")
        if not rp_set <= r_set:
            raise ValueError("r_prime must be a subset of r")

    @property
    def deleted_rows(self) -> frozenset[Row]:
        return frozenset(self.r) - frozenset(self.r_prime)

    @property
    def retained_rows(self) -> frozenset[Row]:
        return frozenset(self.r_prime)


@dataclass
class RepairCheckResult:
    """Unified result of a subset-repair check algorithm."""

    is_repair: bool
    candidate_consistent: bool
    addable_tuple: Optional[Row] = None
    witness_addable_subset: Optional[tuple[Row, ...]] = None
    certificate: dict[str, Any] = field(default_factory=dict)
    build_time_sec: float = 0.0
    check_time_sec: float = 0.0
    total_time_sec: float = 0.0
    index_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Rows may contain non-JSON-friendly values; stringify for logging.
        if self.addable_tuple is not None:
            d["addable_tuple"] = list(self.addable_tuple)
        if self.witness_addable_subset is not None:
            d["witness_addable_subset"] = [list(t) for t in self.witness_addable_subset]
        return d


class RowAdapter:
    """Display helper mapping attribute names to tuple values."""

    def __init__(self, schema: RelationSchema, row: Row) -> None:
        self.schema = schema
        self.row = row

    def as_dict(self) -> dict[str, Any]:
        return {a: self.row[i] for i, a in enumerate(self.schema.attributes)}

    def __getitem__(self, attr: str) -> Any:
        return self.row[self.schema.attr_to_idx[attr]]

    def __repr__(self) -> str:
        return f"RowAdapter({self.as_dict()})"


def rows_to_set(rows: Iterable[Row]) -> set[Row]:
    return set(rows)


def ensure_subset(r: Sequence[Row], r_prime: Sequence[Row]) -> None:
    if not set(r_prime) <= set(r):
        raise ValueError("r_prime is not a subset of r")

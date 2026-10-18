"""Functional dependency utilities: closure, BCNF, satisfaction."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence

from common.types import FD, Row


def attribute_closure(
    attrs: Iterable[str],
    fds: Sequence[FD],
) -> frozenset[str]:
    """Compute attribute closure attrs+ under F using the fixed-point algorithm.

    Example:
        U = {A,B,C}, F = {A->B, B->C}, closure({A}) = {A,B,C}.
    """
    closure: set[str] = set(attrs)
    changed = True
    while changed:
        changed = False
        for fd in fds:
            if fd.lhs_set <= closure and not fd.rhs_set <= closure:
                closure |= fd.rhs_set
                changed = True
    return frozenset(closure)


def is_superkey(
    attrs: Iterable[str],
    U: Iterable[str],
    fds: Sequence[FD],
) -> bool:
    """Return True iff attrs is a superkey of R(U, F), i.e. attrs+ = U."""
    return attribute_closure(attrs, fds) == frozenset(U)


def minimize_superkey(
    X: Iterable[str],
    U: Iterable[str],
    fds: Sequence[FD],
) -> frozenset[str]:
    """Return an inclusion-minimal superkey K ⊆ X by one stable left-to-right pass.

    Algorithm:
        K = X
        for each attribute A in a stable order:
            if closure(K - {A}, F) == U: remove A
    By monotonicity of closure, one pass suffices.
    """
    u_set = frozenset(U)
    # Stable order: sorted for determinism (caller may pass ordered attrs).
    ordered = tuple(sorted(set(X)))
    k: set[str] = set(ordered)
    for a in ordered:
        if a not in k:
            continue
        candidate = k - {a}
        if attribute_closure(candidate, fds) == u_set:
            k = candidate
    return frozenset(k)


def validate_bcnf(U: Iterable[str], fds: Sequence[FD]) -> bool:
    """Check BCNF on the given FDs without enumerating all of F+.

    For every nontrivial FD X->Y in the provided F, require that X is a superkey.
    Formal synthetic schemas are constructed so that every nontrivial FD in the
    input has a superkey left-hand side; this is the engineering validation used
    by schema generators and BCNF algorithms.
    """
    u_set = frozenset(U)
    for fd in fds:
        if fd.is_trivial():
            continue
        if not is_superkey(fd.lhs, u_set, fds):
            return False
    return True


def project_row(
    row: Row,
    attr_names: Sequence[str],
    attr_to_idx: Mapping[str, int],
) -> tuple[Any, ...]:
    """Project a row onto the given attributes (stable order of attr_names)."""
    return tuple(row[attr_to_idx[a]] for a in attr_names)


def satisfies_fd(
    instance: Sequence[Row],
    fd: FD,
    attr_to_idx: Mapping[str, int],
) -> bool:
    """Return True iff instance satisfies a single FD X->Y."""
    if not instance or fd.is_trivial():
        return True
    # Map X-value -> first observed Y-value
    seen: dict[tuple[Any, ...], tuple[Any, ...]] = {}
    for row in instance:
        x = project_row(row, fd.lhs, attr_to_idx)
        y = project_row(row, fd.rhs, attr_to_idx)
        prev = seen.get(x)
        if prev is None:
            seen[x] = y
        elif prev != y:
            return False
    return True


def satisfies_fds(
    instance: Sequence[Row],
    fds: Sequence[FD],
    attr_to_idx: Optional[Mapping[str, int]] = None,
    attributes: Optional[Sequence[str]] = None,
) -> bool:
    """Return True iff instance satisfies every FD in fds.

    If attr_to_idx is omitted, attributes must be provided (or inferred is not
    attempted from rows alone). Prefer passing an explicit mapping.
    """
    if attr_to_idx is None:
        if attributes is None:
            raise ValueError("satisfies_fds requires attr_to_idx or attributes")
        attr_to_idx = {a: i for i, a in enumerate(attributes)}
    for fd in fds:
        if not satisfies_fd(instance, fd, attr_to_idx):
            return False
    return True


def find_fd_violation(
    instance: Sequence[Row],
    fds: Sequence[FD],
    attr_to_idx: Mapping[str, int],
) -> Optional[tuple[FD, Row, Row]]:
    """Find one violating pair (fd, t1, t2), or None if instance satisfies F."""
    for fd in fds:
        if fd.is_trivial():
            continue
        seen: dict[tuple[Any, ...], Row] = {}
        for row in instance:
            x = project_row(row, fd.lhs, attr_to_idx)
            y = project_row(row, fd.rhs, attr_to_idx)
            prev = seen.get(x)
            if prev is None:
                seen[x] = row
            else:
                prev_y = project_row(prev, fd.rhs, attr_to_idx)
                if prev_y != y and prev != row:
                    return (fd, prev, row)
    return None


def nontrivial_fds(fds: Sequence[FD]) -> tuple[FD, ...]:
    """Return nontrivial FDs (rhs notsubseteq lhs)."""
    return tuple(fd for fd in fds if not fd.is_trivial())

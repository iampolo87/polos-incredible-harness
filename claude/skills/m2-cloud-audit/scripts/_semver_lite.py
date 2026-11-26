"""Tiny numeric version comparison for service-version gaps (stdlib-only).

Handles dotted numeric versions like "10.4", "1.2", "8.1", "10.11". Trailing
non-numeric junk is ignored. Not a full semver implementation — patch-level
constraint matching for quality patches is delegated to composer/semver in PHP.
"""
from __future__ import annotations


def parse(v: str) -> tuple[int, ...]:
    parts = []
    for chunk in str(v).split("."):
        num = ""
        for ch in chunk:
            if ch.isdigit():
                num += ch
            else:
                break
        parts.append(int(num) if num else 0)
    return tuple(parts)


def _pad(a: tuple[int, ...], b: tuple[int, ...]):
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)), b + (0,) * (n - len(b))


def compare(a: str, b: str) -> int:
    """Return -1 if a<b, 0 if equal, 1 if a>b."""
    pa, pb = _pad(parse(a), parse(b))
    return (pa > pb) - (pa < pb)


def gte(a: str, b: str) -> bool:
    return compare(a, b) >= 0


def lt(a: str, b: str) -> bool:
    return compare(a, b) < 0

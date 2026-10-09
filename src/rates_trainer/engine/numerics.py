"""Small numerical helpers (stdlib only) so the engine has no third-party dependency."""

from __future__ import annotations

from typing import Callable, Sequence


def find_root(
    f: Callable[[float], float],
    lo: float,
    hi: float,
    tol: float = 1e-14,
    max_iter: int = 200,
) -> float:
    """Bracketed root find (Illinois variant of regula falsi).

    Requires f(lo) and f(hi) to have opposite signs. Converges in a handful of
    iterations for the near-linear residuals produced by curve bootstrapping.
    """
    f_lo, f_hi = f(lo), f(hi)
    if f_lo == 0.0:
        return lo
    if f_hi == 0.0:
        return hi
    if f_lo * f_hi > 0:
        raise ValueError(f"root not bracketed on [{lo}, {hi}]: f={f_lo}, {f_hi}")
    side = 0
    x = lo
    for _ in range(max_iter):
        x = (lo * f_hi - hi * f_lo) / (f_hi - f_lo)
        f_x = f(x)
        if abs(f_x) < tol or abs(hi - lo) < tol:
            return x
        if f_x * f_hi > 0:  # root lies in [lo, x]
            hi, f_hi = x, f_x
            if side == -1:
                f_lo /= 2.0
            side = -1
        else:
            lo, f_lo = x, f_x
            if side == 1:
                f_hi /= 2.0
            side = 1
    return x


def solve_linear(a: Sequence[Sequence[float]], b: Sequence[float]) -> list[float]:
    """Solve a x = b by Gaussian elimination with partial pivoting."""
    n = len(b)
    if len(a) != n or any(len(row) != n for row in a):
        raise ValueError("solve_linear needs a square system")
    m = [list(map(float, row)) + [float(b[i])] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-14:
            raise ValueError("singular system: hedge instruments do not span the risk")
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(col + 1, n):
            factor = m[r][col] / m[col][col]
            for c in range(col, n + 1):
                m[r][c] -= factor * m[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))) / m[r][r]
    return x

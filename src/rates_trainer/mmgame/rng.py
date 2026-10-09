"""Deterministic randomness for the market-making game.

Every random choice comes from a Stream keyed by (seed, *labels): a SHA-256 counter, so the same key always gives the same numbers on any Python version and
no stream depends on how many numbers another stream has used. That is what makes a game replayable from (seed, config, the player's actions): the
bots' arrivals and noise for (round, market, bot) are fixed by the seed alone; only their *decisions* depend on the player's quotes.
"""

from __future__ import annotations

import hashlib
import math

U_BITS = 53


class Stream:
    def __init__(self, seed: int, *labels: object):
        self._key = "|".join(str(x) for x in (seed, *labels)).encode()
        self._n = 0

    def u53(self) -> int:
        h = hashlib.sha256(self._key + b"#" + str(self._n).encode()).digest()
        self._n += 1
        return int.from_bytes(h[:8], "big") >> (64 - U_BITS)

    def u(self) -> float:
        return self.u53() / (1 << U_BITS)

    def chance(self, p: float) -> bool:
        return self.u() < p

    def randint(self, a: int, b: int) -> int:
        """Uniform integer in [a, b]."""
        return a + (self.u53() * (b - a + 1) >> U_BITS)

    def uniform(self, a: float, b: float) -> float:
        return a + (b - a) * self.u()

    def choice(self, seq):
        return seq[self.randint(0, len(seq) - 1)]

    def shuffle(self, seq) -> list:
        out = list(seq)
        for i in range(len(out) - 1, 0, -1):
            j = self.randint(0, i)
            out[i], out[j] = out[j], out[i]
        return out

    def sample(self, seq, k: int) -> list:
        return self.shuffle(seq)[:k]

    def gauss(self, mu: float = 0.0, sd: float = 1.0) -> float:
        u1, u2 = 1.0 - self.u(), self.u()
        return mu + sd * math.sqrt(-2.0 * math.log(u1)) * math.cos(2.0 * math.pi * u2)

    def weighted(self, items: list, weights: list[float]):
        x = self.u() * sum(weights)
        acc = 0.0
        for it, w in zip(items, weights):
            acc += w
            if x < acc:
                return it
        return items[-1]

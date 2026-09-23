"""IQ hisoblash — zamonaviy psixometrik standart bo'yicha.

* Har bir savol uch parametrli IRT modeli (3PL) bilan ifodalanadi:
      P(to'g'ri | θ) = c + (1 − c) / (1 + e^(−1.702·a·(θ − b)))
  b — qiyinlik (⭐1…⭐5 → −2…+2), a — ajratish kuchi, c — taxmin ehtimoli (1/variantlar).
* Qobiliyat θ EAP usulida (N(0,1) prior, posterior o'rtacha) baholanadi —
  hamma javob to'g'ri/xato bo'lsa ham barqaror natija beradi.
* Deviatsion IQ: IQ = 100 + 15·θ (Wechsler/Stanford-Binet shkalasi, M=100, SD=15),
  standart xato SE = 15·σ(θ), 95% ishonch oralig'i = IQ ± 1.96·SE,
  persentil = Φ(θ).
* Darajalar — WAIS-IV tasnifi.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

D = 1.702
A_DEFAULT = 1.2
B_BY_LEVEL = {1: -2.0, 2: -1.0, 3: 0.0, 4: 1.0, 5: 2.0}
IQ_MIN, IQ_MAX = 55, 145
_GRID = [-4.0 + i * 0.02 for i in range(401)]

# WAIS-IV tavsiflovchi toifalari
CLASSES = [
    (130, "Juda yuqori", "🌟"),
    (120, "Yuqori", "🏆"),
    (110, "O'rtachadan yuqori", "🥇"),
    (90, "O'rtacha", "🙂"),
    (80, "O'rtachadan past", "📘"),
    (70, "Chegaraviy", "📙"),
    (-999, "Past", "📕"),
]


@dataclass
class Item:
    difficulty: int
    n_options: int
    correct: bool

    @property
    def b(self) -> float:
        return B_BY_LEVEL.get(self.difficulty, 0.0)

    @property
    def c(self) -> float:
        return 1.0 / max(self.n_options, 2)


@dataclass
class Report:
    theta: float
    se: float
    iq: int
    ci_low: int
    ci_high: int
    percentile: float
    label: str
    emoji: str


def p_correct(theta: float, b: float, a: float = A_DEFAULT, c: float = 0.0) -> float:
    return c + (1 - c) / (1 + math.exp(-D * a * (theta - b)))


def estimate(items: list[Item]) -> tuple[float, float]:
    """EAP bahosi: (θ, posterior SD)."""
    logs = []
    for t in _GRID:
        lp = -t * t / 2
        for it in items:
            p = p_correct(t, it.b, A_DEFAULT, it.c)
            lp += math.log(p if it.correct else 1 - p)
        logs.append(lp)
    top = max(logs)
    w = [math.exp(x - top) for x in logs]
    total = sum(w)
    mean = sum(t * wi for t, wi in zip(_GRID, w)) / total
    var = sum((t - mean) ** 2 * wi for t, wi in zip(_GRID, w)) / total
    return mean, math.sqrt(var)


def classify(iq: int) -> tuple[str, str]:
    for bound, label, emoji in CLASSES:
        if iq >= bound:
            return label, emoji
    return CLASSES[-1][1], CLASSES[-1][2]  # pragma: no cover


def percentile(theta: float) -> float:
    return 50 * (1 + math.erf(theta / math.sqrt(2)))


def _clamp(v: float) -> int:
    return int(max(IQ_MIN, min(IQ_MAX, round(v))))


def report(items: list[Item]) -> Report:
    theta, sd = estimate(items)
    iq = _clamp(100 + 15 * theta)
    se = 15 * sd
    label, emoji = classify(iq)
    return Report(theta=theta, se=se, iq=iq,
                  ci_low=_clamp(100 + 15 * theta - 1.96 * se),
                  ci_high=_clamp(100 + 15 * theta + 1.96 * se),
                  percentile=percentile(theta), label=label, emoji=emoji)

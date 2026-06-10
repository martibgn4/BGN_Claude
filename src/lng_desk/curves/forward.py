"""Forward curve representation.

A `MonthlyForwardCurve` carries forward prices at mid-month sentinel dates, plus
provenance (source, unit). Pricing functions take curves as arguments and never
fetch from a source themselves — keeps pricing pure and reproducible.
"""
from dataclasses import dataclass
from datetime import date
from typing import Mapping


@dataclass(frozen=True)
class MonthlyForwardCurve:
    name: str
    unit: str              # e.g., "USD/MMBtu", "USD/day"
    points: Mapping[date, float]
    source: str            # e.g., "platts:JKM:2026-05-28" or "placeholder"

    def at(self, d: date) -> float:
        return self.points[d]

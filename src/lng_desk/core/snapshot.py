"""MarketSnapshot — bundle of market data needed to price a deal.

A snapshot is the immutable contract between the data layer (Finn) and the pricing
layer (Marti). Every priced number can be traced to a `snapshot_id`.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Mapping

from lng_desk.curves.forward import MonthlyForwardCurve


@dataclass(frozen=True)
class MarketSnapshot:
    """Immutable snapshot of curves, vols, costs as of `valuation_date`.

    curves:
        index curves keyed by IndexFamily.value, e.g., 'TTF', 'JKM', 'HH', 'Brent'.
        TTF/JKM/HH expected in USD/MMBtu, Brent in USD/bbl.
    freight_curves:
        per-MMBtu round-trip freight by route key 'Origin->Destination'.
    regas_costs:
        flat per-MMBtu by destination zone, e.g., {'NWE': 0.40, 'Asia': 0.40}.
    vols:
        annualized lognormal vol of each index, keyed by IndexFamily.value.
    correlations:
        pairwise correlation, key is a frozenset of two index names.
    discount_rate:
        flat continuous USD risk-free for PV. Replace with a curve for production.
    """
    valuation_date: date
    curves: Mapping[str, MonthlyForwardCurve]
    freight_curves: Mapping[str, MonthlyForwardCurve]
    regas_costs: Mapping[str, float]
    vols: Mapping[str, float]
    correlations: Mapping[frozenset[str], float]
    discount_rate: float
    snapshot_id: str        # provenance: 'bloomberg:2026-05-28T16:30Z' or 'placeholder:...'

    def correlation(self, a: str, b: str) -> float:
        if a == b:
            return 1.0
        return self.correlations[frozenset({a, b})]

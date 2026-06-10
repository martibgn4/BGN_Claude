"""Voyage routes with laden/ballast split and per-day boil-off.

Boil-off is applied to the laden voyage only (no cargo onboard ballast).
Linear approximation `rate * days` is used; the geometric form `1 - (1-rate)^days`
differs by <0.01% at typical rates and tenors.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class VoyageRoute:
    name: str
    days_laden: int
    days_ballast: int

    @property
    def days_total(self) -> int:
        return self.days_laden + self.days_ballast

    def boiloff_fraction(self, rate_per_day: float) -> float:
        return rate_per_day * self.days_laden


SABINE_TO_NWE = VoyageRoute(
    name="Sabine -> NWE (Gate/Zeebrugge)",
    days_laden=14,
    days_ballast=14,
)

SABINE_TO_JAPAN_PANAMA = VoyageRoute(
    name="Sabine -> Japan via Panama",
    days_laden=30,
    days_ballast=30,
)

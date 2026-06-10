"""Freight unit conversions.

Charter day-rate forward curves come in USD/day. To use them as a per-MMBtu
freight cost in the pricing engine, amortise across the full round-trip voyage
for the specific route and cargo size.

    freight_per_mmbtu  =  day_rate × (laden + ballast days)  /  cargo_mmbtu

This treats the day rate as the all-in charter cost. For finer accounting
(port fees, canal tolls, fuel cost separate from boil-off), extend voyage.py.
"""
from lng_desk.curves.forward import MonthlyForwardCurve
from lng_desk.freight.voyage import VoyageRoute


def freight_per_mmbtu_from_day_rate(
    day_rate_curve: MonthlyForwardCurve,
    route: VoyageRoute,
    cargo_mmbtu: float,
    route_key: str | None = None,
) -> MonthlyForwardCurve:
    factor = route.days_total / cargo_mmbtu
    return MonthlyForwardCurve(
        name=route_key or f"{day_rate_curve.name} ({route.name})",
        unit="USD/MMBtu",
        points={d: v * factor for d, v in day_rate_curve.points.items()},
        source=(
            f"{day_rate_curve.source};route={route.name};"
            f"days_total={route.days_total};cargo_mmbtu={cargo_mmbtu:.0f}"
        ),
    )

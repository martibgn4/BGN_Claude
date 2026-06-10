"""Snapshot loaders — bundle curves + vols into a MarketSnapshot.

Two sources of truth, both returning the same MarketSnapshot type so the pricing
engine doesn't care which provided the numbers:

    load_snapshot_from_bloomberg()  -- live pull, requires Terminal + blpapi.
                                       Pulls TTF/JKM/HH/Brent indices AND LBE freight.
    load_snapshot_from_cache()      -- replay a previously-cached snapshot
"""
from datetime import date
from pathlib import Path

from lng_desk.core.calendar import monthly_sentinels
from lng_desk.core.snapshot import MarketSnapshot
from lng_desk.curves.forward import MonthlyForwardCurve
from lng_desk.data.cache import load_curve_json, save_curve_json


# ---------------------------------------------------------------------------
# Default risk / cost assumptions
# (Vols, regas, discount: live in the snapshot, not in pricing. These defaults
# are illustrative — wire actual implied vols and contract-specific costs later.)
# ---------------------------------------------------------------------------
DEFAULT_REGAS_COSTS = {"NWE": 0.40, "Asia": 0.40, "Japan": 0.40}
DEFAULT_VOLS = {"TTF": 0.40, "JKM": 0.45, "HH": 0.50, "Brent": 0.30}
DEFAULT_CORRELATIONS = {
    frozenset({"TTF", "JKM"}):   0.75,
    frozenset({"TTF", "HH"}):    0.45,
    frozenset({"JKM", "HH"}):    0.40,
    frozenset({"TTF", "Brent"}): 0.55,
    frozenset({"JKM", "Brent"}): 0.55,
    frozenset({"HH",  "Brent"}): 0.35,
}
DEFAULT_DISCOUNT_RATE = 0.05

DEFAULT_CARGO_MMBTU = 3_700_000.0    # 3.7 TBtu — for $/day -> $/MMBtu conversion

# Routes covered by the default snapshot. Add to ROUTES in freight.routes too
# if you extend this list.
_DEFAULT_ROUTE_KEYS = ("Sabine Pass->NWE", "Sabine Pass->Asia", "Sabine Pass->Japan")


def _safe_route_key(key: str) -> str:
    return key.replace("->", "_").replace(" ", "_")


# ---------------------------------------------------------------------------
# Bloomberg (Finn live pull) — indices and freight
# ---------------------------------------------------------------------------
def load_snapshot_from_bloomberg(
    valuation_date: date,
    year: int = 2027,
    cache_dir: Path | str | None = None,
    cargo_mmbtu: float = DEFAULT_CARGO_MMBTU,
    freight_year_digits: int = 2,
) -> MarketSnapshot:
    """Pull TTF/JKM/HH/Brent indices and LBE freight for `year`, build snapshot.

    LBE day-rate forward (USD/day) is converted to per-MMBtu freight cost for
    each registered route using `freight_per_mmbtu_from_day_rate(curve, route, cargo)`.
    """
    from lng_desk.data.bloomberg import (
        fetch_monthly_curve_native, fetch_ttf_curve_usd_mmbtu,
    )
    from lng_desk.freight.conversion import freight_per_mmbtu_from_day_rate
    from lng_desk.freight.routes import ROUTES

    months = monthly_sentinels(year)

    ttf     = fetch_ttf_curve_usd_mmbtu(months)
    jkm     = fetch_monthly_curve_native("JKM",     months)                                # USD/MMBtu
    hh      = fetch_monthly_curve_native("HH",      months, year_digits=2)                  # USD/MMBtu
    brent   = fetch_monthly_curve_native("Brent",   months)                                # USD/bbl
    freight = fetch_monthly_curve_native("Freight", months, year_digits=freight_year_digits)  # USD/day (LBE)

    atl_route = ROUTES[("Sabine Pass", "NWE")]
    pac_route = ROUTES[("Sabine Pass", "Asia")]
    nwe_freight  = freight_per_mmbtu_from_day_rate(freight, atl_route, cargo_mmbtu, route_key="Sabine Pass->NWE")
    asia_freight = freight_per_mmbtu_from_day_rate(freight, pac_route, cargo_mmbtu, route_key="Sabine Pass->Asia")

    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        save_curve_json(ttf,           cache_dir / f"TTF_{year}.json")
        save_curve_json(jkm,           cache_dir / f"JKM_{year}.json")
        save_curve_json(hh,            cache_dir / f"HH_{year}.json")
        save_curve_json(brent,         cache_dir / f"Brent_{year}.json")
        save_curve_json(freight,       cache_dir / f"Freight_LBE_{year}.json")           # native USD/day
        save_curve_json(nwe_freight,   cache_dir / f"Freight_Sabine_Pass_NWE_{year}.json")
        save_curve_json(asia_freight,  cache_dir / f"Freight_Sabine_Pass_Asia_{year}.json")

    return MarketSnapshot(
        valuation_date=valuation_date,
        curves={"TTF": ttf, "JKM": jkm, "HH": hh, "Brent": brent},
        freight_curves={
            "Sabine Pass->NWE":   nwe_freight,
            "Sabine Pass->Asia":  asia_freight,
            "Sabine Pass->Japan": asia_freight,
        },
        regas_costs=DEFAULT_REGAS_COSTS,
        vols=DEFAULT_VOLS,
        correlations=DEFAULT_CORRELATIONS,
        discount_rate=DEFAULT_DISCOUNT_RATE,
        snapshot_id=f"bloomberg:{valuation_date.isoformat()}",
    )


# ---------------------------------------------------------------------------
# Cache replay
# ---------------------------------------------------------------------------
def load_snapshot_from_cache(
    valuation_date: date,
    cache_dir: Path | str,
    year: int = 2027,
) -> MarketSnapshot:
    cache_dir = Path(cache_dir)
    curves: dict[str, MonthlyForwardCurve] = {}
    for name in ("TTF", "JKM", "HH", "Brent"):
        path = cache_dir / f"{name}_{year}.json"
        if path.exists():
            curves[name] = load_curve_json(path)
    if "TTF" not in curves or "JKM" not in curves:
        raise FileNotFoundError(
            f"Cache at {cache_dir} missing TTF or JKM curves for {year}. "
            f"Run scripts/fetch_curves_bbg_2027.py first."
        )

    freight: dict[str, MonthlyForwardCurve] = {}
    for key in _DEFAULT_ROUTE_KEYS:
        path = cache_dir / f"Freight_{_safe_route_key(key)}_{year}.json"
        if path.exists():
            freight[key] = load_curve_json(path)
    if "Sabine Pass->NWE" not in freight or "Sabine Pass->Asia" not in freight:
        raise FileNotFoundError(
            f"Cache at {cache_dir} missing per-route freight curves for {year}. "
            f"Run scripts/fetch_curves_bbg_2027.py to pull LBE and derive routes."
        )

    return MarketSnapshot(
        valuation_date=valuation_date,
        curves=curves,
        freight_curves=freight,
        regas_costs=DEFAULT_REGAS_COSTS,
        vols=DEFAULT_VOLS,
        correlations=DEFAULT_CORRELATIONS,
        discount_rate=DEFAULT_DISCOUNT_RATE,
        snapshot_id=f"cache:{valuation_date.isoformat()}:{cache_dir.name}",
    )

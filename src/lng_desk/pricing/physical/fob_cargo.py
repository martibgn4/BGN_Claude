"""Pricing primitives for an FOB cargo with index-linked loading and destination choice.

All functions are pure: they take market data + cargo terms and return numbers.
Per-MMBtu quantities are expressed *per MMBtu of LOADED cargo* unless noted; the
boil-off haircut on delivered volume is folded into the netback formula so that
the result can be multiplied by the loaded cargo size to get total $.
"""
from dataclasses import dataclass

from lng_desk.freight.voyage import VoyageRoute


def nwe_netback_per_mmbtu_loaded(
    ttf_m: float,
    route: VoyageRoute,
    freight_usd_mmbtu: float,
    regas_usd_mmbtu: float,
    boiloff_rate_per_day: float,
) -> float:
    """NWE-delivered netback (USD/MMBtu loaded). Assumes DES NWE ≈ TTF (basis ignored)."""
    arr_factor = 1.0 - route.boiloff_fraction(boiloff_rate_per_day)
    return ttf_m * arr_factor - freight_usd_mmbtu - regas_usd_mmbtu * arr_factor


def jkm_netback_per_mmbtu_loaded(
    jkm_m: float,
    route: VoyageRoute,
    freight_usd_mmbtu: float,
    regas_usd_mmbtu: float,
    boiloff_rate_per_day: float,
) -> float:
    """JKM-delivered netback (USD/MMBtu loaded). Assumes DES Japan ≈ JKM (basis ignored)."""
    arr_factor = 1.0 - route.boiloff_fraction(boiloff_rate_per_day)
    return jkm_m * arr_factor - freight_usd_mmbtu - regas_usd_mmbtu * arr_factor


def fob_price_per_mmbtu(ttf_m: float, discount_usd_mmbtu: float) -> float:
    """FOB price under a 'TTF flat minus D' contract."""
    return ttf_m - discount_usd_mmbtu

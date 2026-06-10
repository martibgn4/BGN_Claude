"""Spread option pricing for destination flexibility (closed-form analytical).

Model choice — Bachelier (normal) on the absolute spread:
    Reasons over Margrabe / Kirk for this use case:
    - The relevant random variable is the spread S = JKM_netback - TTF_netback, which
      can and does cross zero; lognormal models (Margrabe / Kirk) constrain each leg
      to positivity and behave poorly when one leg becomes very small.
    - At 6–24 month tenors and the JKM-TTF observed regime (post-2022), the spread
      distribution is closer to normal than lognormal.
    - For production / multi-period path-dependent optionality (sequencing decisions
      across the 12 cargoes), replace this with LSM Monte Carlo.

Spread vol is built from the two legs' GBM diffusions evaluated at the forward levels:
    σ_S² = (σ1 F1)² + (σ2 F2)² - 2 ρ (σ1 F1)(σ2 F2)
This is the instantaneous diffusion of (F1 - F2) when each leg is GBM with vols σ1, σ2.
"""
import math


def _phi(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _N(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bachelier_call(
    forward: float,
    strike: float,
    sigma_annual_abs: float,
    time_to_expiry_years: float,
) -> float:
    """Bachelier call value: E[max(X - K, 0)] where X ~ N(F, σ²T)."""
    if time_to_expiry_years <= 0 or sigma_annual_abs <= 0:
        return max(forward - strike, 0.0)
    sigma_eff = sigma_annual_abs * math.sqrt(time_to_expiry_years)
    d = (forward - strike) / sigma_eff
    return (forward - strike) * _N(d) + sigma_eff * _phi(d)


def spread_volatility_absolute(
    f1: float, sigma1_rel: float,
    f2: float, sigma2_rel: float,
    rho: float,
) -> float:
    """Absolute vol of (F1 - F2) in $/MMBtu/√yr, treating each leg as GBM at its forward."""
    v1 = sigma1_rel * f1
    v2 = sigma2_rel * f2
    var = v1 * v1 + v2 * v2 - 2.0 * rho * v1 * v2
    return math.sqrt(max(var, 0.0))

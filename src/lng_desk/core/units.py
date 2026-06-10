"""Unit conversion helpers.

Conventions for the desk:
- All gas hub prices internally in USD/MMBtu.
- Brent is kept in USD/bbl; slope-indexed price formulas absorb the conversion
  via the slope value itself (e.g., slope = 0.135 means 13.5% Brent in USD/MMBtu).
- 1 MWh = 3.412 MMBtu (gas calorific conversion; ICE TTF spec).
"""

MWH_PER_MMBTU = 1.0 / 3.412   # 1 MMBtu in MWh
MMBTU_PER_MWH = 3.412


def eur_per_mwh_to_usd_per_mmbtu(eur_per_mwh: float, eurusd: float) -> float:
    """Convert TTF EUR/MWh price to USD/MMBtu using spot EURUSD (USD per EUR).

    USD/MMBtu = EUR/MWh × (USD/EUR) × (MWh/MMBtu)
              = EUR/MWh × eurusd / 3.412
    """
    return eur_per_mwh * eurusd / MMBTU_PER_MWH


def gbp_per_therm_to_usd_per_mmbtu(gbp_per_therm: float, gbpusd: float) -> float:
    """Convert NBP GBp/therm to USD/MMBtu. NBP is typically quoted in pence (GBp).

    1 therm = 0.1 MMBtu, so GBp/therm = GBp / 0.1 MMBtu.
    USD/MMBtu = GBp/therm × (1/100 GBP/GBp) × (USD/GBP) × (1/0.1 MMBtu/therm)
              = GBp/therm × gbpusd / 10
    """
    return gbp_per_therm * gbpusd / 10.0

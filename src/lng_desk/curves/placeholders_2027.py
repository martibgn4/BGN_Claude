"""PLACEHOLDER 2027 monthly forward curves.

NOT REAL MARKET DATA. Used to scaffold the pricing pipeline before Finn wires in
Platts/ICE/Spark feeds. Replace before any P&L use.

Shape rationale (illustrative only):
- TTF: winter premium ~$10–10.60 (Jan/Dec), shoulder ~$9.20–9.80, summer ~$8.40–8.70.
- JKM: ~$0.80–1.20 over TTF in winter, ~$0.70–0.90 in summer (cooling demand).
- Freight (per-MMBtu of loaded LNG, round-trip equivalent):
    Atlantic Sabine→NWE: ~28-day round-trip @ ~$60k/day = $1.68M / 3.7M MMBtu ≈ $0.45/MMBtu
    Pacific Sabine→Japan (Panama): ~60-day round-trip @ ~$70k/day = $4.2M / 3.7M MMBtu ≈ $1.14/MMBtu
"""
from datetime import date

from .forward import MonthlyForwardCurve

_M = lambda m: date(2027, m, 15)

# ttf_2027 = MonthlyForwardCurve(
#     name="TTF",
#     unit="USD/MMBtu",
#     points={
#         _M(1): 10.50, _M(2): 10.20, _M(3): 9.50, _M(4): 8.80,
#         _M(5): 8.50,  _M(6): 8.40,  _M(7): 8.50, _M(8): 8.70,
#         _M(9): 9.20,  _M(10): 9.80, _M(11): 10.30, _M(12): 10.60,
#     },
#     source="placeholder:2026-05-28",
# )
#
# jkm_2027 = MonthlyForwardCurve(
#     name="JKM",
#     unit="USD/MMBtu",
#     points={
#         _M(1): 11.50, _M(2): 11.20, _M(3): 10.30, _M(4): 9.50,
#         _M(5): 9.20,  _M(6): 9.30,  _M(7): 9.40,  _M(8): 9.50,
#         _M(9): 9.80,  _M(10): 10.50, _M(11): 11.20, _M(12): 11.50,
#     },
#     source="placeholder:2026-05-28",
# )
#
# freight_atl_2027 = MonthlyForwardCurve(
#     name="FreightAtlantic_Sabine_NWE_perMMBtu",
#     unit="USD/MMBtu",
#     points={_M(m): 0.45 for m in range(1, 13)},
#     source="placeholder:2026-05-28",
# )
#
# freight_pac_2027 = MonthlyForwardCurve(
#     name="FreightPacific_Sabine_Japan_perMMBtu",
#     unit="USD/MMBtu",
#     points={_M(m): 1.14 for m in range(1, 13)},
#     source="placeholder:2026-05-28",
# )

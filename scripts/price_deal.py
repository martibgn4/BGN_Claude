"""Price a deal defined in a folder.

Usage:
    python scripts/price_deal.py <deal_folder>

The folder must contain deal.csv (terms, costs, run config). Optionally a
curves.csv overrides Bloomberg curves on a per-column basis; any column not
fully populated falls back to Bloomberg. See lng_desk.trades.folder for the
deal.csv / curves.csv schemas.

Examples:
    python scripts/price_deal.py deals/sabine_ttf_2027/
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lng_desk.pricing.engine import (
    DealPricing, breakeven_offset_for_primary, price_deal,
)
from lng_desk.trades.costs import DealCosts
from lng_desk.trades.folder import DealFolderContents, load_deal_folder


def _signed(x: float) -> str:
    return f"- ${-x:.3f}" if x < 0 else f"+ ${x:.3f}"


def print_report(
    pricing: DealPricing,
    snapshot,
    alt: str | None,
    contract_offset: float,
    costs: DealCosts,
    index_name: str,
) -> None:
    print("=" * 116)
    print(f"  Deal:        {pricing.deal.name}")
    print(f"  Side:        {pricing.deal.side.value}  "
          f"({len(pricing.deal.cargoes)} cargoes, {pricing.deal.total_volume_tbtu:.1f} TBtu total)")
    print(f"  Contract:    Price = {pricing.deal.cargoes[0].price_formula.slope} * {index_name}_M "
          f"{_signed(contract_offset)}/MMBtu")
    alts_str = ", ".join(pricing.alternate_destinations) or "(none)"
    print(f"  Primary:     {pricing.primary_destination}   |   Alternates: {alts_str}")
    print(f"  Snapshot:    {pricing.snapshot_id}")
    vol_strs = [f"σ_{k}={snapshot.vols[k]:.0%}" for k in ("TTF", "JKM")]
    print(f"  r={snapshot.discount_rate:.1%}  {'  '.join(vol_strs)}  "
          f"ρ(TTF,JKM)={snapshot.correlation('TTF','JKM'):.2f}")
    print("=" * 116)
    print()

    if alt is not None:
        hdr = (f"{'Month':<9}{'TTF':>7}{'JKM':>7}{'FOB':>7}"
               f"{'nb'+pricing.primary_destination:>9}{'nb'+alt:>9}"
               f"{'i_'+pricing.primary_destination:>9}{'i_'+alt:>9}"
               f"{'spr':>7}{'σspr':>7}{'ext/MM':>8}"
               f"{'pri($M)':>9}{'ext($M)':>9}")
        print(hdr); print("-" * len(hdr))
        for r in pricing.cargo_results:
            ttf = snapshot.curves["TTF"].at(r.delivery_month)
            jkm = snapshot.curves["JKM"].at(r.delivery_month)
            print(
                f"{r.delivery_month:%Y-%m}  "
                f"{ttf:>6.2f} {jkm:>6.2f} {r.fob_price_per_mmbtu:>6.2f} "
                f"{r.primary_netback_per_mmbtu:>8.2f} {r.alt_netbacks[alt]:>8.2f} "
                f"{r.primary_intrinsic_per_mmbtu:>8.3f} {r.alt_intrinsic_per_mmbtu[alt]:>8.3f} "
                f"{r.alt_forward_spread[alt]:>6.3f} {r.alt_spread_vol[alt]:>6.2f} "
                f"{r.alt_extrinsic_per_mmbtu[alt]:>7.3f} "
                f"{r.primary_intrinsic_usd/1e6:>8.2f} {r.alt_extrinsic_usd[alt]/1e6:>8.2f}"
            )
    else:
        hdr = (f"{'Month':<9}{'TTF':>7}{'FOB':>7}"
               f"{'nb'+pricing.primary_destination:>9}{'i_'+pricing.primary_destination:>9}"
               f"{'pri($M)':>9}")
        print(hdr); print("-" * len(hdr))
        for r in pricing.cargo_results:
            ttf = snapshot.curves["TTF"].at(r.delivery_month)
            print(
                f"{r.delivery_month:%Y-%m}  "
                f"{ttf:>6.2f} {r.fob_price_per_mmbtu:>6.2f} "
                f"{r.primary_netback_per_mmbtu:>8.2f} {r.primary_intrinsic_per_mmbtu:>8.3f} "
                f"{r.primary_intrinsic_usd/1e6:>8.2f}"
            )

    gross_pri   = pricing.total_primary_gross_intrinsic_usd
    total_pri   = pricing.total_primary_intrinsic_usd
    total_ext   = pricing.total_extrinsic_usd(alt) if alt else 0.0
    total       = total_pri + total_ext
    breakeven   = breakeven_offset_for_primary(pricing, snapshot)
    cost_lines  = pricing.total_costs_breakdown_usd
    total_costs = pricing.total_costs_usd

    print()
    print("-" * 116)
    print(f"  Gross primary intrinsic ({pricing.primary_destination}, pre-cost):       "
          f"${gross_pri/1e6:>12,.2f} m")
    if total_costs != 0 or any(v != 0 for v in cost_lines.values()):
        print(f"  Costs (PV, primary destination):")
        for label in ("financing", "hedging", "extra", "port", "emission"):
            v = cost_lines[label]
            if v != 0:
                print(f"    {label:<10}                                 ${-v/1e6:>12,.2f} m")
        print(f"    {'TOTAL':<10}                                 ${-total_costs/1e6:>12,.2f} m")
    print(f"  Net primary intrinsic ({pricing.primary_destination}, after costs):    "
          f"${total_pri/1e6:>12,.2f} m")
    if alt is not None:
        print(f"  Extrinsic vs {alt} (diversion option, cost-adjusted): "
              f"${total_ext/1e6:>12,.2f} m")
    print(f"  Deal value:                                      ${total/1e6:>12,.2f} m")
    print()
    print(f"  Breakeven offset (net primary-intrinsic = 0):  {_signed(breakeven)}/MMBtu")
    print(f"    (Price = {pricing.deal.cargoes[0].price_formula.slope} * {index_name}_M "
          f"{_signed(breakeven)}/MMBtu makes primary leg zero NPV after costs)")
    if alt is not None and costs is not None:
        port_alt = costs.port_usd(alt) / 1e6
        emis_alt = costs.emission_usd(alt) / 1e6
        if port_alt != 0 or emis_alt != 0:
            print(f"  (note: alt-destination port/emission "
                  f"[{alt}: port=${port_alt:.2f}M, emis=${emis_alt:.2f}M per cargo] "
                  f"already shifted into the extrinsic spread)")
    print("=" * 116)


def main() -> int:
    ap = argparse.ArgumentParser(description="Price a deal defined in a folder.")
    ap.add_argument("folder", help="Path to deal folder containing deal.csv (+ optional curves.csv).")
    ap.add_argument("--cache-dir", default="data/raw/bloomberg/2027",
                    help="Bloomberg cache dir for curves not provided in curves.csv.")
    args = ap.parse_args()

    cache_dir = Path(__file__).resolve().parent.parent / args.cache_dir
    contents = load_deal_folder(args.folder, fallback_cache_dir=cache_dir)

    pricing = price_deal(
        deal=contents.deal,
        snapshot=contents.snapshot,
        primary_destination=contents.primary_destination,
        alternate_destinations=contents.alternate_destinations,
        boiloff_rate_per_day=contents.boiloff_rate_per_day,
        costs=contents.costs,
    )

    alt = contents.alternate_destinations[0] if contents.alternate_destinations else None
    index_name = contents.deal.cargoes[0].price_formula.index.value
    print_report(
        pricing, contents.snapshot,
        alt=alt,
        contract_offset=contents.contract_offset_for_report,
        costs=contents.costs,
        index_name=index_name,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

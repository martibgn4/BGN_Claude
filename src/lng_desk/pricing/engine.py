"""Generic deal pricer.

Takes a Deal + MarketSnapshot + buyer-side destination view and returns intrinsic,
extrinsic, and per-cargo decomposition. Same machinery prices FOB TTF-indexed,
FOB HH-toll, DES NWE, Brent-slope, etc.

Buyer-side modelling:
    primary_destination:    where intrinsic is marked (e.g., 'NWE' for an FOB
                            cargo the buyer will primarily run to Europe).
    alternate_destinations: each alternate yields an extrinsic value via a
                            Bachelier call on the netback spread vs primary.
"""
import math
from dataclasses import dataclass, field
from datetime import date

from lng_desk.core.snapshot import MarketSnapshot
from lng_desk.core.calendar import years_between
from lng_desk.freight.routes import get_route
from lng_desk.pricing.extrinsic.spread_option import (
    bachelier_call, spread_volatility_absolute,
)
from lng_desk.trades.costs import DealCosts
from lng_desk.trades.deal import Cargo, Deal, IncoTerms, IndexFamily


# ---------------------------------------------------------------------------
# Destination netback (FOB cargo, buyer perspective)
# ---------------------------------------------------------------------------
def _delivered_index_for(destination: str) -> str:
    """Map a destination zone to its anchoring price index."""
    if destination == "NWE":
        return IndexFamily.TTF.value
    if destination in ("Asia", "Japan"):
        return IndexFamily.JKM.value
    raise ValueError(f"No delivered-price index defined for destination '{destination}'")


def _netback_per_mmbtu_loaded(
    cargo: Cargo,
    destination: str,
    snapshot: MarketSnapshot,
    boiloff_rate_per_day: float,
) -> tuple[float, float]:
    """Return (netback_per_mmbtu_loaded, vol_carrying_index_value).

    The second value is the index forward at the delivery month (boil-off-scaled
    by the arrival factor), used downstream as the per-leg forward for spread-
    option vol calculation.
    """
    if cargo.incoterms is not IncoTerms.FOB:
        raise NotImplementedError(f"Pricing for {cargo.incoterms} not implemented yet")

    route = get_route(cargo.origin, destination)
    arr_factor = 1.0 - route.boiloff_fraction(boiloff_rate_per_day)

    delivered_index_name = _delivered_index_for(destination)
    delivered_index = snapshot.curves[delivered_index_name].at(cargo.delivery_month)

    freight_key = f"{cargo.origin}->{destination}"
    freight = snapshot.freight_curves[freight_key].at(cargo.delivery_month)
    regas = snapshot.regas_costs[destination]

    netback = delivered_index * arr_factor - freight - regas * arr_factor
    leg_forward = delivered_index * arr_factor
    return netback, leg_forward


def _fob_price_per_mmbtu(cargo: Cargo, snapshot: MarketSnapshot) -> float:
    idx_value = snapshot.curves[cargo.price_formula.index.value].at(cargo.delivery_month)
    return cargo.price_formula.evaluate(idx_value)


# ---------------------------------------------------------------------------
# Result objects
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CargoPricing:
    delivery_month: date
    discount_factor: float
    fob_price_per_mmbtu: float
    primary_destination: str
    primary_netback_per_mmbtu: float
    # Net of costs (intrinsic AFTER financing/hedging/extra + port/emission at primary):
    primary_intrinsic_per_mmbtu: float
    primary_intrinsic_usd: float
    # Gross intrinsic (pre-cost) kept for reporting / cost attribution:
    primary_gross_intrinsic_usd: float
    # PV USD cost components for this cargo at the primary destination:
    financing_usd: float
    hedging_usd: float
    extra_usd: float
    port_usd: float
    emission_usd: float
    # Alt-destination decomposition. alt_intrinsic_per_mmbtu and alt_forward_spread
    # are NET of costs (i.e., cost-adjusted netbacks). Extrinsic uses the
    # cost-adjusted spread.
    alt_netbacks: dict[str, float]
    alt_intrinsic_per_mmbtu: dict[str, float]
    alt_forward_spread: dict[str, float]
    alt_spread_vol: dict[str, float]
    alt_extrinsic_per_mmbtu: dict[str, float]
    alt_extrinsic_usd: dict[str, float]


@dataclass(frozen=True)
class DealPricing:
    deal: Deal
    snapshot_id: str
    primary_destination: str
    alternate_destinations: tuple[str, ...]
    cargo_results: tuple[CargoPricing, ...]

    @property
    def total_primary_intrinsic_usd(self) -> float:
        return sum(c.primary_intrinsic_usd for c in self.cargo_results)

    @property
    def total_primary_gross_intrinsic_usd(self) -> float:
        return sum(c.primary_gross_intrinsic_usd for c in self.cargo_results)

    def total_extrinsic_usd(self, alt: str) -> float:
        return sum(c.alt_extrinsic_usd[alt] for c in self.cargo_results)

    @property
    def total_extrinsic_all_alts_usd(self) -> float:
        return sum(self.total_extrinsic_usd(a) for a in self.alternate_destinations)

    @property
    def total_deal_value_usd(self) -> float:
        return self.total_primary_intrinsic_usd + self.total_extrinsic_all_alts_usd

    @property
    def total_costs_breakdown_usd(self) -> dict[str, float]:
        """PV USD by cost component, summed across cargoes (primary destination)."""
        return {
            "financing": sum(c.financing_usd for c in self.cargo_results),
            "hedging":   sum(c.hedging_usd   for c in self.cargo_results),
            "extra":     sum(c.extra_usd     for c in self.cargo_results),
            "port":      sum(c.port_usd      for c in self.cargo_results),
            "emission":  sum(c.emission_usd  for c in self.cargo_results),
        }

    @property
    def total_costs_usd(self) -> float:
        return sum(self.total_costs_breakdown_usd.values())


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
def price_deal(
    deal: Deal,
    snapshot: MarketSnapshot,
    primary_destination: str,
    alternate_destinations: tuple[str, ...] = (),
    boiloff_rate_per_day: float = 0.00075,
    costs: DealCosts | None = None,
) -> DealPricing:
    """Price every cargo, return decomposed results.

    Costs:
        Flat per-MMBtu costs (financing, hedging, extra) reduce primary intrinsic
        but cancel in the spread between destinations, so do not affect extrinsic.
        Per-cargo fixed costs (port, emission) are looked up by destination; they
        reduce primary intrinsic AND shift the spread used to value the diversion
        option, so they do affect extrinsic.
    """
    costs = costs or DealCosts()
    cargo_results: list[CargoPricing] = []

    for cargo in deal.cargoes:
        T = years_between(snapshot.valuation_date, cargo.delivery_month)
        df = math.exp(-snapshot.discount_rate * T)
        fob = _fob_price_per_mmbtu(cargo, snapshot)
        V = cargo.volume_mmbtu

        flat_pm = costs.flat_per_mmbtu_total
        fixed_primary_usd_undisc = costs.fixed_usd(primary_destination)
        fixed_primary_pm = fixed_primary_usd_undisc / V

        primary_nb, primary_leg_fwd = _netback_per_mmbtu_loaded(
            cargo, primary_destination, snapshot, boiloff_rate_per_day,
        )
        gross_primary_intr_usd = (primary_nb - fob) * V * df
        primary_intr_pm  = (primary_nb - fob) - flat_pm - fixed_primary_pm
        primary_intr_usd = primary_intr_pm * V * df

        # PV USD of each cost line at this cargo (primary destination)
        financing_pv = costs.financing_per_mmbtu * V * df
        hedging_pv   = costs.hedging_per_mmbtu   * V * df
        extra_pv     = costs.extra_per_mmbtu     * V * df
        port_pv      = costs.port_usd(primary_destination)     * df
        emission_pv  = costs.emission_usd(primary_destination) * df

        alt_netbacks: dict[str, float] = {}
        alt_intr_pm:  dict[str, float] = {}
        alt_spread:   dict[str, float] = {}
        alt_sigma:    dict[str, float] = {}
        alt_ext_pm:   dict[str, float] = {}
        alt_ext_usd:  dict[str, float] = {}

        primary_idx_name = _delivered_index_for(primary_destination)
        sigma_primary = snapshot.vols[primary_idx_name]

        for alt in alternate_destinations:
            alt_nb, alt_leg_fwd = _netback_per_mmbtu_loaded(
                cargo, alt, snapshot, boiloff_rate_per_day,
            )
            alt_netbacks[alt] = alt_nb

            fixed_alt_pm = costs.fixed_usd(alt) / V
            alt_intr_pm[alt] = (alt_nb - fob) - flat_pm - fixed_alt_pm

            # Cost-adjusted spread used by the diversion option:
            # (alt_nb - fixed_alt/V) - (primary_nb - fixed_primary/V).
            # Flat per-MMBtu costs and fob cancel out — only the destination-
            # dependent costs shift the spread.
            spread = (alt_nb - fixed_alt_pm) - (primary_nb - fixed_primary_pm)
            alt_spread[alt] = spread

            alt_idx_name = _delivered_index_for(alt)
            sigma_alt = snapshot.vols[alt_idx_name]
            rho = snapshot.correlation(primary_idx_name, alt_idx_name)

            sigma_spread = spread_volatility_absolute(
                f1=alt_leg_fwd, sigma1_rel=sigma_alt,
                f2=primary_leg_fwd, sigma2_rel=sigma_primary,
                rho=rho,
            )
            alt_sigma[alt] = sigma_spread

            ext_pm = bachelier_call(
                forward=spread, strike=0.0,
                sigma_annual_abs=sigma_spread,
                time_to_expiry_years=T,
            )
            alt_ext_pm[alt] = ext_pm
            alt_ext_usd[alt] = ext_pm * V * df

        cargo_results.append(CargoPricing(
            delivery_month=cargo.delivery_month,
            discount_factor=df,
            fob_price_per_mmbtu=fob,
            primary_destination=primary_destination,
            primary_netback_per_mmbtu=primary_nb,
            primary_intrinsic_per_mmbtu=primary_intr_pm,
            primary_intrinsic_usd=primary_intr_usd,
            primary_gross_intrinsic_usd=gross_primary_intr_usd,
            financing_usd=financing_pv,
            hedging_usd=hedging_pv,
            extra_usd=extra_pv,
            port_usd=port_pv,
            emission_usd=emission_pv,
            alt_netbacks=alt_netbacks,
            alt_intrinsic_per_mmbtu=alt_intr_pm,
            alt_forward_spread=alt_spread,
            alt_spread_vol=alt_sigma,
            alt_extrinsic_per_mmbtu=alt_ext_pm,
            alt_extrinsic_usd=alt_ext_usd,
        ))

    return DealPricing(
        deal=deal,
        snapshot_id=snapshot.snapshot_id,
        primary_destination=primary_destination,
        alternate_destinations=tuple(alternate_destinations),
        cargo_results=tuple(cargo_results),
    )


def breakeven_offset_for_primary(
    pricing: DealPricing,
    snapshot: MarketSnapshot,
) -> float:
    """Offset (USD/MMBtu added to price formula) that makes primary-intrinsic = 0.

    Positive offset means seller charges more; negative means buyer gets discount.
    For an 'FOB = TTF + offset' deal where current intrinsic is negative, the
    breakeven offset is negative — i.e., buyer needs the discount.
    """
    pv_volume = sum(
        c.discount_factor *
        next(cc.volume_mmbtu for cc in pricing.deal.cargoes if cc.delivery_month == c.delivery_month)
        for c in pricing.cargo_results
    )
    # new_intrinsic = old_intrinsic - O * pv_volume = 0  =>  O = old_intrinsic / pv_volume
    return pricing.total_primary_intrinsic_usd / pv_volume

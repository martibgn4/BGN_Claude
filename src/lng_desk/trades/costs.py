"""Deal-level cost components — costs the buyer bears on top of the FOB price.

These costs reduce the primary-destination intrinsic of the deal. Costs that
depend on destination (port, emission) also shift the diversion-option spread
and hence the extrinsic. Flat per-MMBtu costs (financing, hedging, extra) do
not affect the extrinsic since they cancel out of the spread between destinations.

Per-MMBtu costs charge against the LOADED cargo volume.
Port and emission are per-cargo flat USD costs, stored internally in USD.
Use `DealCosts.from_millions(...)` to enter port/emission in million USD.
"""
from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class DealCosts:
    financing_per_mmbtu: float = 0.0
    hedging_per_mmbtu:   float = 0.0
    extra_per_mmbtu:     float = 0.0
    port_usd_by_destination:     Mapping[str, float] = field(default_factory=dict)
    emission_usd_by_destination: Mapping[str, float] = field(default_factory=dict)

    @classmethod
    def from_millions(
        cls,
        *,
        financing_per_mmbtu: float = 0.0,
        hedging_per_mmbtu:   float = 0.0,
        extra_per_mmbtu:     float = 0.0,
        port_musd_by_destination:     Mapping[str, float] | None = None,
        emission_musd_by_destination: Mapping[str, float] | None = None,
    ) -> "DealCosts":
        """Build a DealCosts where port/emission inputs are in MILLION USD."""
        return cls(
            financing_per_mmbtu=financing_per_mmbtu,
            hedging_per_mmbtu=hedging_per_mmbtu,
            extra_per_mmbtu=extra_per_mmbtu,
            port_usd_by_destination={
                k: v * 1e6 for k, v in (port_musd_by_destination or {}).items()
            },
            emission_usd_by_destination={
                k: v * 1e6 for k, v in (emission_musd_by_destination or {}).items()
            },
        )

    @property
    def flat_per_mmbtu_total(self) -> float:
        return self.financing_per_mmbtu + self.hedging_per_mmbtu + self.extra_per_mmbtu

    def port_usd(self, destination: str) -> float:
        return self.port_usd_by_destination.get(destination, 0.0)

    def emission_usd(self, destination: str) -> float:
        return self.emission_usd_by_destination.get(destination, 0.0)

    def fixed_usd(self, destination: str) -> float:
        """Total per-cargo flat USD cost (port + emission) for a destination."""
        return self.port_usd(destination) + self.emission_usd(destination)

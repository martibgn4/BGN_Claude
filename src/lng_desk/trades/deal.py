"""Deal, Cargo, and PriceFormula data structures.

Captures the contractual terms of a multi-cargo LNG sale or purchase. Pricing logic
lives in lng_desk.pricing.engine; this module is pure data.

The PriceFormula captures the index-linked pricing convention:
    price_per_mmbtu = slope * index_value + offset

where the index_value is in the contractual native units of that index:
    - TTF, JKM, HH:  USD/MMBtu  (slope is dimensionless, usually ~1.0 or 1.15 for HH+toll)
    - Brent:         USD/bbl    (slope absorbs the unit conversion; e.g., 0.135 = 13.5%)

Examples:
    FOB Sabine TTF flat:           PriceFormula(IndexFamily.TTF,   slope=1.00, offset= 0.00)
    FOB Sabine TTF minus $0.95:    PriceFormula(IndexFamily.TTF,   slope=1.00, offset=-0.95)
    FOB Sabine 115% HH + $2.50:    PriceFormula(IndexFamily.HH,    slope=1.15, offset=+2.50)
    DES Asia 13.5% Brent + $0.30:  PriceFormula(IndexFamily.BRENT, slope=0.135, offset=+0.30)
"""
from dataclasses import dataclass
from datetime import date
from enum import Enum


class IndexFamily(str, Enum):
    TTF = "TTF"
    JKM = "JKM"
    HH = "HH"
    BRENT = "Brent"


class IncoTerms(str, Enum):
    FOB = "FOB"
    DES = "DES"
    CIF = "CIF"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class PriceFormula:
    index: IndexFamily
    slope: float
    offset: float            # USD/MMBtu

    def evaluate(self, index_value: float) -> float:
        """Apply the formula to a snapshot index value. Result in USD/MMBtu."""
        return self.slope * index_value + self.offset


@dataclass(frozen=True)
class Cargo:
    delivery_month: date     # mid-month sentinel matching forward-curve keys
    volume_tbtu: float
    incoterms: IncoTerms
    origin: str              # 'Sabine Pass', 'Ras Laffan', ...
    contractual_destination: str | None   # set for DES; None for FOB (buyer chooses)
    price_formula: PriceFormula

    @property
    def volume_mmbtu(self) -> float:
        return self.volume_tbtu * 1_000_000


@dataclass(frozen=True)
class Deal:
    name: str
    counterparty: str
    side: Side
    cargoes: tuple[Cargo, ...]

    @property
    def total_volume_tbtu(self) -> float:
        return sum(c.volume_tbtu for c in self.cargoes)

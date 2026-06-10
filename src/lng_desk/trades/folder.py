"""Folder-based deal loader: deal.csv (+ optional curves.csv) -> ready-to-price bundle.

A deal folder is a directory containing:

  deal.csv     Required. Key/value CSV with deal terms, costs, and run config.
  curves.csv   Optional. Wide CSV: 'month' column + one column per curve.
               Any column populated for ALL target months overrides the corresponding
               Bloomberg pull. Partial / blank columns fall back to Bloomberg.

deal.csv keys (required marked *):

  Deal identity:
    name*                       free text
    counterparty                default "UNSPECIFIED"
    side                        "buy" or "sell", default "buy"

  Deal terms:
    year*                       e.g. 2027 (builds 12 monthly cargoes)
    volume_tbtu_per_cargo*      e.g. 3.7
    origin*                     e.g. "Sabine Pass" (must match freight.routes registry)
    incoterms                   "FOB" / "DES" / "CIF", default "FOB"

  Price formula (price = slope * index + offset, in USD/MMBtu out):
    index*                      "TTF" / "JKM" / "HH" / "Brent"
    slope                       default 1.0
    offset                      default 0.0 (or use 'ttf_discount' shorthand: offset = -ttf_discount)
    ttf_discount                shorthand for a TTF-indexed FOB minus a discount D

  Pricing run:
    primary_destination*        e.g. "NWE"
    alternate_destinations      pipe- or comma-separated, e.g. "Asia" or "Asia|Japan"
    valuation_date*             YYYY-MM-DD
    boiloff_per_day             default 0.00075
    discount_rate               default 0.05

  Costs:
    financing_per_mmbtu         USD/MMBtu (default 0)
    hedging_per_mmbtu           USD/MMBtu (default 0)
    extra_per_mmbtu             USD/MMBtu (default 0)
    port_musd:<DEST>            million USD per cargo at <DEST>, e.g. port_musd:NWE,0.5
    emission_musd:<DEST>        million USD per cargo at <DEST>

curves.csv layout (header row + unit row + monthly data):

    month,TTF,JKM,HH,Brent,Freight_Sabine_Pass_NWE,Freight_Sabine_Pass_Asia
    unit,USD/MMBtu,USD/MMBtu,USD/MMBtu,USD/bbl,USD/day,USD/day
    2027-01,...
    2027-02,...

  - The 'unit' row (right after the header, with literal 'unit' as first cell)
    declares each column's unit. Freight columns may be USD/day (auto-converted
    to per-MMBtu using the route's voyage days and the deal's cargo size) OR
    USD/MMBtu (used directly). Gas indices must be USD/MMBtu; Brent must be
    USD/bbl. If the unit row is absent, defaults are inferred (back-compat).
  - A column is only used if it has a non-empty value for EVERY target month.
    Partial / blank columns fall back to a Bloomberg pull.
"""
import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from lng_desk.core.calendar import monthly_sentinels
from lng_desk.core.snapshot import MarketSnapshot
from lng_desk.curves.forward import MonthlyForwardCurve
from lng_desk.trades.costs import DealCosts
from lng_desk.trades.deal import (
    Cargo, Deal, IncoTerms, IndexFamily, PriceFormula, Side,
)


# Curve columns we know how to map. Brent is USD/bbl, everything else USD/MMBtu.
_INDEX_COLUMNS = ("TTF", "JKM", "HH", "Brent")
_FREIGHT_ROUTE_TO_COL = {
    "Sabine Pass->NWE":  "Freight_Sabine_Pass_NWE",
    "Sabine Pass->Asia": "Freight_Sabine_Pass_Asia",
}


@dataclass(frozen=True)
class DealFolderContents:
    deal: Deal
    costs: DealCosts
    snapshot: MarketSnapshot
    primary_destination: str
    alternate_destinations: tuple[str, ...]
    boiloff_rate_per_day: float
    folder_path: Path
    contract_offset_for_report: float


# ---------------------------------------------------------------------------
# CSV readers
# ---------------------------------------------------------------------------
def _read_kv_csv(path: Path) -> dict[str, str]:
    """Read deal.csv as key/value pairs. Skips blanks and #-comment lines."""
    out: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        first = True
        for row in reader:
            if not row or all(c.strip() == "" for c in row):
                continue
            if row[0].lstrip().startswith("#"):
                continue
            if first:
                first = False
                if row[0].strip().lower() in ("key", "name") and len(row) >= 2 \
                        and row[1].strip().lower() in ("value", "val"):
                    continue  # header row
            if len(row) < 2:
                continue
            k = row[0].strip()
            v = row[1].strip() if len(row) > 1 else ""
            if k:
                out[k] = v
    return out


def _parse_month(s: str) -> date:
    """Parse 'YYYY-MM' or 'YYYY-MM-DD' -> mid-month sentinel."""
    parts = s.strip().split("-")
    return date(int(parts[0]), int(parts[1]), 15)


def _read_curves_csv(path: Path, months: list[date]) -> dict[str, MonthlyForwardCurve]:
    """Read wide curves.csv with the required header layout:

        month,<col_1>,<col_2>,...
        unit,<unit_1>,<unit_2>,...
        2027-01,<v11>,<v12>,...
        2027-02,...

    The 'unit' row is identified by its first cell being literally 'unit'. The
    declared unit lands on the resulting MonthlyForwardCurve and downstream code
    interprets it (e.g., USD/day freight gets voyage-converted in _build_snapshot).
    If the unit row is absent, defaults are inferred (USD/bbl for Brent, USD/MMBtu
    for everything else) for back-compat.

    Only columns with a non-empty value for EVERY month in `months` are returned;
    partial / blank columns fall back to Bloomberg upstream.
    """
    if not path.exists():
        return {}

    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = [r for r in csv.reader(f) if r and not all(c.strip() == "" for c in r)]
    if len(rows) < 2:
        return {}

    header = [c.strip() for c in rows[0]]
    try:
        month_idx = next(i for i, c in enumerate(header) if c.lower() == "month")
    except StopIteration:
        return {}

    data_rows = rows[1:]
    units_by_col: dict[str, str] = {}
    if data_rows and month_idx < len(data_rows[0]) and data_rows[0][month_idx].strip().lower() == "unit":
        unit_row = data_rows[0]
        for i, col in enumerate(header):
            if i == month_idx or i >= len(unit_row):
                continue
            units_by_col[col] = unit_row[i].strip()
        data_rows = data_rows[1:]

    # Index rows by month
    rows_by_month: dict[date, list[str]] = {}
    for row in data_rows:
        if month_idx >= len(row):
            continue
        ms = row[month_idx].strip()
        if not ms:
            continue
        try:
            m = _parse_month(ms)
        except (ValueError, IndexError):
            continue
        rows_by_month[m] = row

    result: dict[str, MonthlyForwardCurve] = {}
    for i, col in enumerate(header):
        if i == month_idx:
            continue
        points: dict[date, float] = {}
        complete = True
        for m in months:
            row = rows_by_month.get(m)
            if row is None or i >= len(row):
                complete = False
                break
            raw = row[i].strip()
            if raw == "":
                complete = False
                break
            try:
                points[m] = float(raw)
            except ValueError:
                complete = False
                break
        if complete and points:
            declared = units_by_col.get(col, "")
            unit = declared or ("USD/bbl" if col == "Brent" else "USD/MMBtu")
            result[col] = MonthlyForwardCurve(
                name=col, unit=unit, points=points,
                source=f"csv:{path.name}",
            )
    return result


# ---------------------------------------------------------------------------
# deal.csv -> Deal/DealCosts/run config
# ---------------------------------------------------------------------------
def _get(d: dict[str, str], key: str, default: str | None = None) -> str:
    raw = d.get(key, "").strip()
    if raw == "":
        if default is None:
            raise KeyError(f"deal.csv missing required key: {key!r}")
        return default
    return raw


def _getf(d: dict[str, str], key: str, default: float | None = None) -> float:
    raw = d.get(key, "").strip()
    if raw == "":
        if default is None:
            raise KeyError(f"deal.csv missing required key: {key!r}")
        return default
    return float(raw)


def _split_dests(s: str) -> tuple[str, ...]:
    if not s.strip():
        return ()
    sep = "|" if "|" in s else ","
    return tuple(x.strip() for x in s.split(sep) if x.strip())


def _scan_keyed(d: dict[str, str], prefix: str) -> dict[str, float]:
    """Find keys 'prefix:KEY' -> {KEY: float(value)}."""
    out: dict[str, float] = {}
    for k, v in d.items():
        if k.startswith(prefix + ":"):
            dest = k[len(prefix) + 1:].strip()
            vs = v.strip()
            if dest and vs:
                out[dest] = float(vs)
    return out


def _build_deal(cfg: dict[str, str]) -> tuple[Deal, float]:
    """Returns (Deal, contract_offset_for_report)."""
    name         = _get(cfg, "name", "Unnamed deal")
    counterparty = _get(cfg, "counterparty", "UNSPECIFIED")
    side         = Side.BUY if _get(cfg, "side", "buy").lower() == "buy" else Side.SELL

    year         = int(_get(cfg, "year"))
    volume_tbtu  = _getf(cfg, "volume_tbtu_per_cargo")
    origin       = _get(cfg, "origin")
    incoterms    = IncoTerms(_get(cfg, "incoterms", "FOB").upper())

    index_family = IndexFamily(_get(cfg, "index"))
    slope        = _getf(cfg, "slope", 1.0)
    if "ttf_discount" in cfg and cfg["ttf_discount"].strip() != "" and "offset" not in cfg:
        offset = -_getf(cfg, "ttf_discount")
    else:
        offset = _getf(cfg, "offset", 0.0)
    formula = PriceFormula(index=index_family, slope=slope, offset=offset)

    cargoes = tuple(
        Cargo(
            delivery_month=m,
            volume_tbtu=volume_tbtu,
            incoterms=incoterms,
            origin=origin,
            contractual_destination=None,
            price_formula=formula,
        )
        for m in monthly_sentinels(year)
    )
    return Deal(name=name, counterparty=counterparty, side=side, cargoes=cargoes), offset


def _build_costs(cfg: dict[str, str]) -> DealCosts:
    return DealCosts.from_millions(
        financing_per_mmbtu=_getf(cfg, "financing_per_mmbtu", 0.0),
        hedging_per_mmbtu=_getf(cfg, "hedging_per_mmbtu", 0.0),
        extra_per_mmbtu=_getf(cfg, "extra_per_mmbtu", 0.0),
        port_musd_by_destination=_scan_keyed(cfg, "port_musd"),
        emission_musd_by_destination=_scan_keyed(cfg, "emission_musd"),
    )


# ---------------------------------------------------------------------------
# Snapshot assembly: CSV overrides + Bloomberg fallback
# ---------------------------------------------------------------------------
_EXPECTED_INDEX_UNITS = {"TTF": "USD/MMBtu", "JKM": "USD/MMBtu", "HH": "USD/MMBtu", "Brent": "USD/bbl"}


def _validate_index_unit(name: str, curve: MonthlyForwardCurve) -> None:
    expected = _EXPECTED_INDEX_UNITS[name]
    if curve.unit and curve.unit != expected:
        raise ValueError(
            f"curves.csv: column {name!r} declared unit {curve.unit!r}, expected {expected!r}. "
            f"For TTF in EUR/MWh or NBP in GBp/therm, convert externally for now "
            f"(or extend folder._build_snapshot to call lng_desk.core.units helpers + an FX feed)."
        )


def _convert_freight_if_day_rate(
    route_key: str,
    curve: MonthlyForwardCurve,
    cargo_mmbtu: float,
) -> MonthlyForwardCurve:
    """If curve.unit is USD/day, apply route's voyage conversion. Else use as-is."""
    if curve.unit == "USD/day":
        from lng_desk.freight.conversion import freight_per_mmbtu_from_day_rate
        from lng_desk.freight.routes import ROUTES
        origin, dest = route_key.split("->", 1)
        route = ROUTES[(origin, dest)]
        return freight_per_mmbtu_from_day_rate(curve, route, cargo_mmbtu, route_key=route_key)
    if curve.unit and curve.unit != "USD/MMBtu":
        raise ValueError(
            f"curves.csv: freight column for {route_key!r} declared unit {curve.unit!r}; "
            f"expected USD/day or USD/MMBtu."
        )
    return curve


def _build_snapshot(
    cfg: dict[str, str],
    folder: Path,
    fallback_cache_dir: Path | str | None,
) -> MarketSnapshot:
    from lng_desk.data.snapshot_loader import (
        DEFAULT_CORRELATIONS, DEFAULT_REGAS_COSTS, DEFAULT_VOLS,
    )

    year = int(_get(cfg, "year"))
    val_date = date.fromisoformat(_get(cfg, "valuation_date"))
    discount_rate = _getf(cfg, "discount_rate", 0.05)
    cargo_mmbtu = _getf(cfg, "volume_tbtu_per_cargo") * 1_000_000.0
    months = monthly_sentinels(year)

    csv_curves = _read_curves_csv(folder / "curves.csv", months)

    missing_indices = [n for n in _INDEX_COLUMNS if n not in csv_curves]
    missing_freight = [r for r, col in _FREIGHT_ROUTE_TO_COL.items() if col not in csv_curves]
    sources_used = ["csv:" + ",".join(sorted(csv_curves.keys()))] if csv_curves else []

    bbg_snap = None
    if missing_indices or missing_freight:
        from lng_desk.data.snapshot_loader import load_snapshot_from_bloomberg
        bbg_snap = load_snapshot_from_bloomberg(
            val_date, year=year, cache_dir=fallback_cache_dir,
        )
        sources_used.append(f"bloomberg:{','.join(missing_indices + missing_freight)}")

    indices_out: dict[str, MonthlyForwardCurve] = {}
    for name in _INDEX_COLUMNS:
        if name in csv_curves:
            _validate_index_unit(name, csv_curves[name])
            indices_out[name] = csv_curves[name]
        else:
            indices_out[name] = bbg_snap.curves[name]

    freight_out: dict[str, MonthlyForwardCurve] = {}
    for route, col in _FREIGHT_ROUTE_TO_COL.items():
        if col in csv_curves:
            freight_out[route] = _convert_freight_if_day_rate(route, csv_curves[col], cargo_mmbtu)
        else:
            freight_out[route] = bbg_snap.freight_curves[route]
    # Japan == Asia routing
    freight_out["Sabine Pass->Japan"] = freight_out["Sabine Pass->Asia"]

    return MarketSnapshot(
        valuation_date=val_date,
        curves=indices_out,
        freight_curves=freight_out,
        regas_costs=DEFAULT_REGAS_COSTS,
        vols=DEFAULT_VOLS,
        correlations=DEFAULT_CORRELATIONS,
        discount_rate=discount_rate,
        snapshot_id=f"folder({folder.name})[{';'.join(sources_used) or 'csv'}]:{val_date.isoformat()}",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def load_deal_folder(
    folder: Path | str,
    fallback_cache_dir: Path | str | None = None,
) -> DealFolderContents:
    folder = Path(folder)
    deal_csv = folder / "deal.csv"
    if not deal_csv.exists():
        raise FileNotFoundError(f"Missing deal.csv in folder: {folder}")

    cfg = _read_kv_csv(deal_csv)

    deal, contract_offset = _build_deal(cfg)
    costs = _build_costs(cfg)
    snapshot = _build_snapshot(cfg, folder, fallback_cache_dir)

    primary  = _get(cfg, "primary_destination")
    alt_list = _split_dests(_get(cfg, "alternate_destinations", ""))
    boiloff  = _getf(cfg, "boiloff_per_day", 0.00075)

    return DealFolderContents(
        deal=deal,
        costs=costs,
        snapshot=snapshot,
        primary_destination=primary,
        alternate_destinations=alt_list,
        boiloff_rate_per_day=boiloff,
        folder_path=folder,
        contract_offset_for_report=contract_offset,
    )

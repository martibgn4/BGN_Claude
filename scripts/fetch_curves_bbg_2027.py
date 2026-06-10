"""Finn driver: pull 2027 forward curves from Bloomberg and cache to disk.

Pulls TTF/JKM/HH/Brent indices AND LBE freight day-rate; converts LBE to
per-MMBtu freight for Sabine Pass routes.

Requires:
    - Bloomberg Terminal running locally
    - blpapi installed (see lng_desk.data.bloomberg for install command)

Run:
    python scripts/fetch_curves_bbg_2027.py

Caches JSON to data/raw/bloomberg/2027/. The pricing script picks them up via
load_snapshot_from_cache().
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lng_desk.data.snapshot_loader import load_snapshot_from_bloomberg


def main() -> int:
    valuation_date = date.today()
    cache_dir = Path(__file__).resolve().parent.parent / "data" / "raw" / "bloomberg" / "2027"
    cache_dir.mkdir(parents=True, exist_ok=True)

    print(f"Pulling 2027 curves from Bloomberg (asof={valuation_date}) -> {cache_dir}")
    try:
        snap = load_snapshot_from_bloomberg(valuation_date, year=2027, cache_dir=cache_dir)
    except ImportError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"ERROR: Bloomberg fetch failed: {e}", file=sys.stderr)
        return 1

    print(f"Snapshot id: {snap.snapshot_id}")
    print("Indices:")
    for name, curve in snap.curves.items():
        n = len(curve.points)
        lo = min(curve.points.values()); hi = max(curve.points.values())
        print(f"  {name:<8} ({curve.unit:<10}) {n} pts, range [{lo:.3f}, {hi:.3f}]")
    print("Freight (LBE day-rate -> per-MMBtu by route):")
    for key, curve in snap.freight_curves.items():
        n = len(curve.points)
        lo = min(curve.points.values()); hi = max(curve.points.values())
        print(f"  {key:<22} ({curve.unit:<10}) {n} pts, range [{lo:.3f}, {hi:.3f}]")
    print(f"Cached to {cache_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

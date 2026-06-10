"""JSON cache for forward curves and snapshots.

Lightweight cache so that a Bloomberg fetch can be persisted and re-loaded
without re-querying the Terminal. For larger time-series data, switch to Parquet.
"""
import json
from datetime import date
from pathlib import Path

from lng_desk.curves.forward import MonthlyForwardCurve


def save_curve_json(curve: MonthlyForwardCurve, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": curve.name,
        "unit": curve.unit,
        "source": curve.source,
        "points": {d.isoformat(): v for d, v in curve.points.items()},
    }
    path.write_text(json.dumps(payload, indent=2))


def load_curve_json(path: str | Path) -> MonthlyForwardCurve:
    path = Path(path)
    raw = json.loads(path.read_text())
    points = {date.fromisoformat(k): float(v) for k, v in raw["points"].items()}
    return MonthlyForwardCurve(
        name=raw["name"],
        unit=raw["unit"],
        source=raw["source"],
        points=points,
    )

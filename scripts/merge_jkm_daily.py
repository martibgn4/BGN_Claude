"""Validate a daily JKM settlements.csv and merge it into the master file.

Usage:
    python scripts/merge_jkm_daily.py data/raw/jkm_settlements/2026-07-02/settlements.csv

The daily CSV must have the schema (header row):
    strip_label, settlement, source_screenshot

The merge is idempotent on the settlement_date axis: re-running for the same date
REPLACES the prior rows for that date in the master, rather than duplicating them.
The settlement_date is inferred from the parent folder name (must be YYYY-MM-DD).
"""
import argparse
import csv
import sys
from datetime import date
from pathlib import Path


MONTH_CODES = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
    "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
    "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}


def parse_strip_to_iso(strip: str) -> str:
    """Parse strip label to ISO-ish month code.

    Examples:
        'Aug26'             -> '2026-08'
        'Jul-27'            -> '2027-07'
        'Bal Month (Jul)'   -> 'bal:2026-07' (year inferred outside; left literal here)
        'Q3 26'             -> 'q3:2026-q3'
    """
    s = strip.strip()
    if not s:
        return ""
    if s.lower().startswith("bal month") or s.lower().startswith("balmo"):
        # 'Bal Month (Jul)' -> 'bal:Jul'
        inner = s.split("(")[-1].rstrip(")").strip()
        return f"bal:{inner}" if inner else "bal"
    # Try Mmm + yy
    s2 = s.replace("-", "").replace(" ", "")
    if len(s2) >= 5 and s2[:3].title() in MONTH_CODES:
        mm = MONTH_CODES[s2[:3].title()]
        yy = s2[3:5]
        if yy.isdigit():
            return f"20{yy}-{mm}"
    return s  # passthrough for anything else (Q1/Q2/Cal-yr/etc.)


def read_daily(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        return [r for r in csv.DictReader(f)
                if (r.get("strip_label") or "").strip() != ""]


def validate(rows: list[dict]) -> list[str]:
    errs: list[str] = []
    if not rows:
        errs.append("No data rows in daily CSV")
        return errs
    seen = set()
    for i, r in enumerate(rows, start=2):
        strip = (r.get("strip_label") or "").strip()
        if strip in seen:
            errs.append(f"Row {i}: duplicate strip_label {strip!r}")
        seen.add(strip)
        try:
            v = float((r.get("settlement") or "").strip())
        except ValueError:
            errs.append(f"Row {i}: settlement not numeric ({r.get('settlement')!r})")
            continue
        if not (0.0 < v < 100.0):
            errs.append(f"Row {i}: settlement {v} outside sanity bounds (0, 100)")
    return errs


def read_master(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


MASTER_COLS = ["settlement_date", "strip_label", "month_iso", "settlement", "source_screenshot"]


def write_master(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MASTER_COLS)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in MASTER_COLS})


def main() -> int:
    ap = argparse.ArgumentParser(description="Merge daily JKM settlements into master.")
    ap.add_argument("daily_csv", help="Path to daily settlements.csv (parent folder name = YYYY-MM-DD)")
    ap.add_argument("--master", default="data/raw/jkm_settlements/master.csv",
                    help="Master file path (relative to repo root or absolute).")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    daily_path = Path(args.daily_csv).resolve()
    master_path = Path(args.master)
    if not master_path.is_absolute():
        master_path = repo_root / master_path

    if not daily_path.exists():
        print(f"ERROR: daily CSV not found: {daily_path}", file=sys.stderr)
        return 2

    settlement_date = daily_path.parent.name
    try:
        date.fromisoformat(settlement_date)
    except ValueError:
        print(f"ERROR: parent folder name {settlement_date!r} is not YYYY-MM-DD", file=sys.stderr)
        return 2

    daily_rows = read_daily(daily_path)
    errs = validate(daily_rows)
    if errs:
        for e in errs:
            print(f"  VALIDATION: {e}", file=sys.stderr)
        return 1

    # Drop any existing master rows for this settlement_date; replace with current daily.
    existing = read_master(master_path)
    kept = [r for r in existing if r.get("settlement_date") != settlement_date]
    replaced_count = len(existing) - len(kept)

    new_rows: list[dict] = []
    for r in daily_rows:
        strip = r["strip_label"].strip()
        new_rows.append({
            "settlement_date":   settlement_date,
            "strip_label":       strip,
            "month_iso":         parse_strip_to_iso(strip),
            "settlement":        r["settlement"].strip(),
            "source_screenshot": (r.get("source_screenshot") or "").strip(),
        })

    write_master(master_path, kept + new_rows)

    print(f"OK  date={settlement_date}  rows_added={len(new_rows)}  rows_replaced={replaced_count}  "
          f"master_total={len(kept) + len(new_rows)}  ->  {master_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

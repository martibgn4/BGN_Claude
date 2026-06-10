"""Calendar helpers for delivery-month indexing and time-to-expiry."""
from datetime import date


def years_between(d1: date, d2: date) -> float:
    return (d2 - d1).days / 365.25


def monthly_sentinels(year: int) -> list[date]:
    """Mid-month sentinel dates for each month of `year` (used as forward-curve keys)."""
    return [date(year, m, 15) for m in range(1, 13)]

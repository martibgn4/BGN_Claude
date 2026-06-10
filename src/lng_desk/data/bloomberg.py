"""Bloomberg data adapter (Finn) — direct blpapi, no DataFrame wrapper.

Returns plain Python dicts. No xbbg / pdblp / polars / pandas dependency.

Requires:
    - Bloomberg Terminal running locally (default Desktop API on localhost:8194)
    - blpapi installed from Bloomberg's repo:
        python -m pip install --index-url=https://blpapi.bloomberg.com/repository/releases/python/simple/ blpapi

Bloomberg roots (user-provided 2026-05-28):
    TTF     -> TZT   (EUR/MWh native — converted to USD/MMBtu via EURUSD)
    HH      -> NG    (USD/MMBtu native)
    JKM     -> JKL   (USD/MMBtu native)
    Brent   -> CO    (USD/bbl native — kept in bbl; slope contracts convert)
    Freight -> LBE   (USD/day native — convert via voyage to USD/MMBtu per route)

Futures month codes:
    F=Jan G=Feb H=Mar J=Apr K=May M=Jun N=Jul Q=Aug U=Sep V=Oct X=Nov Z=Dec
"""
import contextlib
from datetime import date, datetime, timezone
from typing import Iterable, Iterator

from lng_desk.core.units import eur_per_mwh_to_usd_per_mmbtu
from lng_desk.curves.forward import MonthlyForwardCurve

MONTH_CODES = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
}

ROOTS = {
    "TTF":     "TZT",
    "HH":      "NG",
    "JKM":     "JKL",
    "Brent":   "CO",
    "Freight": "LBE",
}

NATIVE_UNITS = {
    "TTF":     "EUR/MWh",
    "HH":      "USD/MMBtu",
    "JKM":     "USD/MMBtu",
    "Brent":   "USD/bbl",
    "Freight": "USD/day",
}

_BBG_HOST = "localhost"
_BBG_PORT = 8194


# ---------------------------------------------------------------------------
# Ticker construction
# ---------------------------------------------------------------------------
def bbg_monthly_ticker(
    root: str,
    year: int,
    month: int,
    yellow_key: str = "Comdty",
    year_digits: int = 1,
) -> str:
    """Build a Bloomberg ticker for a specific monthly contract.

    year_digits=1 matches Bloomberg's default for the active near-term range
    (e.g., TZTF7 = Jan 2027 when queried in 2026). Switch to 2 if the contract
    is far enough out that decade ambiguity matters (TZTF27 Comdty).
    """
    code = MONTH_CODES[month]
    if year_digits == 1:
        return f"{root}{code}{year % 10} {yellow_key}"
    if year_digits == 2:
        return f"{root}{code}{year % 100:02d} {yellow_key}"
    raise ValueError(f"year_digits must be 1 or 2, got {year_digits}")


# ---------------------------------------------------------------------------
# blpapi plumbing
# ---------------------------------------------------------------------------
def _import_blpapi():
    try:
        import blpapi
        return blpapi
    except ImportError as e:
        raise ImportError(
            "blpapi not installed. Install from Bloomberg's repo:\n"
            "  python -m pip install --index-url=https://blpapi.bloomberg.com/"
            "repository/releases/python/simple/ blpapi\n"
            "and ensure the Bloomberg Terminal is running locally."
        ) from e


@contextlib.contextmanager
def _bbg_session() -> Iterator:
    """Yield a started blpapi Session with //blp/refdata open. Stops on exit."""
    blpapi = _import_blpapi()
    opts = blpapi.SessionOptions()
    opts.setServerHost(_BBG_HOST)
    opts.setServerPort(_BBG_PORT)
    session = blpapi.Session(opts)
    if not session.start():
        raise RuntimeError(
            f"Failed to start blpapi Session at {_BBG_HOST}:{_BBG_PORT}. "
            "Is the Bloomberg Terminal running and logged in on this machine?"
        )
    if not session.openService("//blp/refdata"):
        session.stop()
        raise RuntimeError("Failed to open //blp/refdata service")
    try:
        yield session
    finally:
        session.stop()


def _bdp(tickers: list[str], fields: list[str]) -> dict[str, dict[str, float | None]]:
    """ReferenceDataRequest -> {ticker: {field: value or None}}.

    Missing values surface as None (not raised); the caller decides how to handle.
    Numeric coercion via getElementAsFloat — non-numeric fields stay None.
    """
    blpapi = _import_blpapi()
    result: dict[str, dict[str, float | None]] = {
        t: {f: None for f in fields} for t in tickers
    }

    with _bbg_session() as session:
        svc = session.getService("//blp/refdata")
        request = svc.createRequest("ReferenceDataRequest")
        for t in tickers:
            request.append("securities", t)
        for f in fields:
            request.append("fields", f)
        session.sendRequest(request)

        while True:
            event = session.nextEvent(timeout=5000)
            for msg in event:
                if not msg.hasElement("securityData"):
                    continue
                security_data = msg.getElement("securityData")
                n = security_data.numValues()
                for i in range(n):
                    sec = security_data.getValueAsElement(i)
                    ticker = sec.getElementAsString("security")
                    if sec.hasElement("securityError"):
                        # Bad ticker / no entitlement — leave values as None
                        continue
                    if not sec.hasElement("fieldData"):
                        continue
                    field_data = sec.getElement("fieldData")
                    for f in fields:
                        if not field_data.hasElement(f):
                            continue
                        try:
                            result[ticker][f] = field_data.getElementAsFloat(f)
                        except Exception:
                            # Field exists but isn't numeric (e.g., ticker metadata) — leave None
                            pass
            if event.eventType() == blpapi.Event.RESPONSE:
                break

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def fetch_spot(ticker: str, field: str = "PX_LAST") -> float:
    data = _bdp([ticker], [field])
    v = data[ticker][field]
    if v is None:
        raise ValueError(f"Bloomberg returned no value for {ticker}/{field}")
    return float(v)


def fetch_monthly_curve_native(
    asset_name: str,
    months: Iterable[date],
    field: str = "PX_LAST",
    yellow_key: str = "Comdty",
    year_digits: int = 1,
) -> MonthlyForwardCurve:
    """Pull a forward curve from Bloomberg in its native units.

    Caller handles unit conversion. For TTF EUR/MWh -> USD/MMBtu, use
    fetch_ttf_curve_usd_mmbtu which combines the curve pull with the FX pull.
    """
    if asset_name not in ROOTS:
        raise ValueError(f"Unknown asset '{asset_name}'. Known: {list(ROOTS)}")
    root = ROOTS[asset_name]

    months_list = list(months)
    tickers_by_month = {
        d: bbg_monthly_ticker(root, d.year, d.month, yellow_key, year_digits)
        for d in months_list
    }
    tickers = list(tickers_by_month.values())
    data = _bdp(tickers, [field])

    points: dict[date, float] = {}
    missing: list[str] = []
    for d, t in tickers_by_month.items():
        v = data.get(t, {}).get(field)
        if v is None:
            missing.append(t)
        else:
            points[d] = float(v)

    if missing:
        raise ValueError(
            f"Bloomberg returned no value for {len(missing)} ticker(s): "
            f"{missing[:5]}{'...' if len(missing) > 5 else ''}\n"
            "Check entitlement, ticker syntax (try year_digits=2 for longer-dated), "
            "or whether the contract is listed for that month."
        )

    return MonthlyForwardCurve(
        name=asset_name,
        unit=NATIVE_UNITS[asset_name],
        points=points,
        source=f"bloomberg:{root}:{field}:{datetime.now(timezone.utc).isoformat(timespec='seconds')}",
    )


def fetch_ttf_curve_usd_mmbtu(
    months: Iterable[date],
    field: str = "PX_LAST",
    eurusd_ticker: str = "EURUSD Curncy",
) -> MonthlyForwardCurve:
    """Pull TTF monthly forwards (EUR/MWh) and convert to USD/MMBtu at spot EURUSD."""
    native = fetch_monthly_curve_native("TTF", months, field=field)
    fx = fetch_spot(eurusd_ticker, "PX_LAST")
    converted = {d: eur_per_mwh_to_usd_per_mmbtu(v, fx) for d, v in native.points.items()}
    return MonthlyForwardCurve(
        name="TTF",
        unit="USD/MMBtu",
        points=converted,
        source=f"{native.source};fx={eurusd_ticker}@{fx:.5f}",
    )

"""Fit the 3-state regime HMM on a returns series and walk-forward backtest it.

DATA IS A TODO. The `returns` DataFrame below is a placeholder. Wire it to real
EOD returns for TTF / HH / Brent (e.g. from the Bloomberg adapter or a CSV).
Until then the script runs on a synthetic regime-switching series so you can see
the full pipeline working and sanity-check the plots.

Usage:
    python scripts/run_hmm_strategy.py                 # synthetic demo, all columns
    python scripts/run_hmm_strategy.py --column TTF    # one column
    python scripts/run_hmm_strategy.py --strategy threshold --tau 0.6
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np
import pandas as pd

from lng_desk.hmm import HiddenMarkovModel, walk_forward_backtest


# ---------------------------------------------------------------------------
# TODO: REPLACE THIS with the real returns DataFrame.
# Target shape: DateTimeIndex (business days), columns = ["TTF", "HH", "Brent"],
# values = daily EOD returns (decimal, e.g. 0.012 = +1.2%). One column per
# underlying. The rest of this script consumes any such frame unchanged.
#
# Likely wiring later:
#   from lng_desk.data.bloomberg import fetch_monthly_curve_native  # or a spot/price pull
#   prices = <pull front-month or spot price history for TZT, NG, CO>
#   returns = np.log(prices).diff().dropna()        # log returns
# ---------------------------------------------------------------------------
def load_returns() -> pd.DataFrame:
    """PLACEHOLDER synthetic data. Replace with real TTF/HH/Brent EOD returns."""
    rng = np.random.default_rng(42)
    n = 2000

    # Simulate a 3-regime Markov chain to produce a realistic-looking series.
    # bear: mu<0 high vol | neutral: mu~0 low vol | bull: mu>0 mid vol
    mu = np.array([-0.0015, 0.0000, 0.0010])
    sd = np.array([0.025, 0.008, 0.014])
    A = np.array([
        [0.94, 0.05, 0.01],
        [0.04, 0.92, 0.04],
        [0.01, 0.05, 0.94],
    ])
    states = np.empty(n, dtype=int)
    states[0] = 1
    for t in range(1, n):
        states[t] = rng.choice(3, p=A[states[t - 1]])
    cols = {}
    for name in ("TTF", "HH", "Brent"):
        eps = rng.normal(size=n)
        cols[name] = mu[states] + sd[states] * eps
    idx = pd.bdate_range("2018-01-01", periods=n)
    df = pd.DataFrame(cols, index=idx)
    df.attrs["synthetic"] = True
    df.attrs["true_states"] = states
    return df


def fit_and_report(name: str, r: np.ndarray, dates, args) -> None:
    print("=" * 78)
    print(f"  {name}")
    print("=" * 78)

    # --- Full-sample fit, just to display the regime parameters ---
    model = HiddenMarkovModel(
        n_states=3,
        n_restarts=args.restarts,
        pin_neutral_zero=args.pin_neutral,
        enforce_sign=args.enforce_sign,
        random_state=0,
    ).fit(r)
    p = model.params_
    labels = ["bear", "neutral", "bull"]
    print(f"  Fitted regimes (sorted by mean, log-lik={model.log_likelihood_:.1f}):")
    print(f"    {'state':<9}{'mu (daily)':>13}{'sigma (daily)':>15}{'ann.mu':>10}{'ann.vol':>10}")
    for k in range(3):
        print(f"    {labels[k]:<9}{p.mu[k]:>13.5f}{np.sqrt(p.sigma2[k]):>15.5f}"
              f"{p.mu[k]*252:>10.1%}{np.sqrt(p.sigma2[k]*252):>10.1%}")
    persist = np.diag(p.A)
    print(f"  State persistence (diag A): "
          f"bear={persist[0]:.2f} neutral={persist[1]:.2f} bull={persist[2]:.2f}")
    print(f"  Stationary dist: " + ", ".join(
        f"{lab}={v:.2f}" for lab, v in zip(labels, _stationary(p.A))))

    # --- Walk-forward backtest ---
    strat_kwargs = {}
    if args.strategy == "kelly":
        strat_kwargs = {"risk_aversion": args.risk_aversion, "leverage_cap": args.leverage}
    elif args.strategy == "threshold":
        strat_kwargs = {"tau": args.tau}

    result = walk_forward_backtest(
        r, dates=dates,
        train_window=args.train_window,
        refit_every=args.refit_every,
        strategy=args.strategy,
        cost_bps=args.cost_bps,
        no_trade_band=args.no_trade_band,
        model_kwargs={
            "n_states": 3, "n_restarts": args.restarts,
            "pin_neutral_zero": args.pin_neutral, "enforce_sign": args.enforce_sign,
        },
        strategy_kwargs=strat_kwargs,
    )
    print()
    print(result.summary())
    print()


def _stationary(A: np.ndarray) -> np.ndarray:
    vals, vecs = np.linalg.eig(A.T)
    i = np.argmin(np.abs(vals - 1.0))
    v = np.real(vecs[:, i])
    return v / v.sum()


def main() -> int:
    ap = argparse.ArgumentParser(description="Regime HMM strategy on daily returns.")
    ap.add_argument("--column", default=None, help="Single column to run (default: all).")
    ap.add_argument("--strategy", default="kelly", choices=("kelly", "threshold", "tanh"))
    ap.add_argument("--train-window", type=int, default=1260)
    ap.add_argument("--refit-every", type=int, default=21)
    ap.add_argument("--restarts", type=int, default=8)
    ap.add_argument("--cost-bps", type=float, default=1.0)
    ap.add_argument("--no-trade-band", type=float, default=0.05)
    ap.add_argument("--risk-aversion", type=float, default=3.0)
    ap.add_argument("--leverage", type=float, default=1.0)
    ap.add_argument("--tau", type=float, default=0.55)
    ap.add_argument("--pin-neutral", action="store_true", help="Pin mu_neutral = 0.")
    ap.add_argument("--enforce-sign", action="store_true", help="Clip bear<=0<=bull.")
    args = ap.parse_args()

    returns = load_returns()
    if returns.attrs.get("synthetic"):
        print("NOTE: running on SYNTHETIC placeholder data. Wire load_returns() to "
              "real TTF/HH/Brent EOD returns (see TODO in this script).\n")

    cols = [args.column] if args.column else list(returns.columns)
    for c in cols:
        series = returns[c].dropna()
        fit_and_report(c, series.to_numpy(), list(series.index), args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

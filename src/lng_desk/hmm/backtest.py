"""Walk-forward backtest harness for the regime-switching strategy.

Discipline enforced here:
  - Fit on a trailing window ending at t-1; trade the position on day t's return.
  - Refit only every `refit_every` days (daily refit adds noise + cost).
  - Transaction cost charged on position changes (turnover).
  - All reported metrics are out-of-sample.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from lng_desk.hmm.model import HiddenMarkovModel
from lng_desk.hmm.strategy import (
    apply_no_trade_band, kelly_position, tanh_position, threshold_position,
)


@dataclass
class BacktestResult:
    dates: list           # length N_oos
    positions: np.ndarray         # target position held into each oos day
    strat_returns: np.ndarray     # net strategy returns (after cost)
    asset_returns: np.ndarray     # underlying returns over the oos window
    beliefs: np.ndarray           # (N_oos, K) filtered P(s_t | r_{1:t})
    metrics: dict = field(default_factory=dict)

    def summary(self) -> str:
        m = self.metrics
        lines = [
            "Walk-forward backtest (out-of-sample)",
            f"  Days traded:        {len(self.strat_returns)}",
            f"  Strategy Sharpe:    {m['sharpe']:.2f}   (asset {m['asset_sharpe']:.2f})",
            f"  Ann. return:        {m['ann_return']:.1%}  (asset {m['asset_ann_return']:.1%})",
            f"  Ann. vol:           {m['ann_vol']:.1%}  (asset {m['asset_ann_vol']:.1%})",
            f"  Max drawdown:       {m['max_drawdown']:.1%}  (asset {m['asset_max_drawdown']:.1%})",
            f"  Calmar:             {m['calmar']:.2f}",
            f"  Hit rate (dir.):    {m['hit_rate']:.1%}",
            f"  Avg gross exposure: {m['avg_abs_position']:.2f}",
            f"  Annual turnover:    {m['annual_turnover']:.1f}x",
            f"  Total cost drag:    {m['total_cost']:.1%}",
        ]
        return "\n".join(lines)


def _annualization(periods_per_year: int) -> float:
    return float(np.sqrt(periods_per_year))


def _max_drawdown(equity: np.ndarray) -> float:
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    return float(dd.min())


def _metrics(strat: np.ndarray, asset: np.ndarray, positions: np.ndarray,
             cost_paid: np.ndarray, ppy: int) -> dict:
    ann = _annualization(ppy)

    def sharpe(x):
        s = x.std()
        return float(x.mean() / s * ann) if s > 0 else 0.0

    strat_equity = np.cumprod(1.0 + strat)
    asset_equity = np.cumprod(1.0 + asset)

    ann_ret = float(strat.mean() * ppy)
    asset_ann_ret = float(asset.mean() * ppy)
    # directional hit rate on days we took a non-zero position
    active = positions != 0
    hits = (np.sign(positions[active]) == np.sign(asset[active]))
    hit_rate = float(hits.mean()) if active.any() else 0.0
    turnover = float(np.abs(np.diff(np.concatenate([[0.0], positions]))).sum())
    n_years = max(len(strat) / ppy, 1e-9)
    max_dd = _max_drawdown(strat_equity)

    return {
        "sharpe": sharpe(strat),
        "asset_sharpe": sharpe(asset),
        "ann_return": ann_ret,
        "asset_ann_return": asset_ann_ret,
        "ann_vol": float(strat.std() * ann),
        "asset_ann_vol": float(asset.std() * ann),
        "max_drawdown": max_dd,
        "asset_max_drawdown": _max_drawdown(asset_equity),
        "calmar": float(ann_ret / abs(max_dd)) if max_dd < 0 else 0.0,
        "hit_rate": hit_rate,
        "avg_abs_position": float(np.abs(positions).mean()),
        "annual_turnover": turnover / n_years,
        "total_cost": float(cost_paid.sum()),
        "final_equity": float(strat_equity[-1]),
    }


def walk_forward_backtest(
    returns: np.ndarray,
    dates=None,
    *,
    train_window: int = 1260,          # ~5y of daily data
    refit_every: int = 21,             # refit monthly
    strategy: str = "kelly",           # "kelly" | "threshold" | "tanh"
    cost_bps: float = 1.0,             # round-trip cost per unit turnover, in bps
    no_trade_band: float = 0.05,
    periods_per_year: int = 252,
    model_kwargs: dict | None = None,
    strategy_kwargs: dict | None = None,
) -> BacktestResult:
    """Run the rolling-window backtest. Returns out-of-sample series + metrics."""
    returns = np.asarray(returns, dtype=float).ravel()
    n = returns.size
    if n <= train_window + 1:
        raise ValueError(f"Need > train_window+1 = {train_window+1} obs, got {n}")
    if dates is None:
        dates = list(range(n))
    model_kwargs = model_kwargs or {}
    strategy_kwargs = strategy_kwargs or {}
    cost_per_unit = cost_bps / 1e4

    positions, strat_rets, asset_rets, beliefs, costs, oos_dates = [], [], [], [], [], []
    model: HiddenMarkovModel | None = None
    current_pos = 0.0

    for t in range(train_window, n):
        # Refit on trailing window [t-train_window, t-1] (no look-ahead).
        if model is None or (t - train_window) % refit_every == 0:
            window = returns[t - train_window : t]
            model = HiddenMarkovModel(**model_kwargs).fit(window)

        # Filter on history up to and including t-1; decide position for day t.
        hist = returns[t - train_window : t]
        belief = model.filter(hist)[-1]                    # P(s_{t-1} | r_{..t-1})
        next_state = model.predict_next_state(belief)
        exp_ret, exp_var = model.predict_return_moments(belief)

        if strategy == "kelly":
            target = kelly_position(exp_ret, exp_var, **strategy_kwargs)
        elif strategy == "threshold":
            target = threshold_position(next_state, **strategy_kwargs)
        elif strategy == "tanh":
            target = tanh_position(exp_ret, **strategy_kwargs)
        else:
            raise ValueError(f"Unknown strategy {strategy!r}")

        target = apply_no_trade_band(target, current_pos, band=no_trade_band)

        # Cost charged on the change in position; P&L realized on day t.
        turnover = abs(target - current_pos)
        cost = turnover * cost_per_unit
        r_t = returns[t]
        net = target * r_t - cost

        positions.append(target)
        strat_rets.append(net)
        asset_rets.append(r_t)
        beliefs.append(belief)
        costs.append(cost)
        oos_dates.append(dates[t])
        current_pos = target

    positions = np.array(positions)
    strat_rets = np.array(strat_rets)
    asset_rets = np.array(asset_rets)
    beliefs = np.array(beliefs)
    costs = np.array(costs)
    metrics = _metrics(strat_rets, asset_rets, positions, costs, periods_per_year)

    return BacktestResult(
        dates=oos_dates,
        positions=positions,
        strat_returns=strat_rets,
        asset_returns=asset_rets,
        beliefs=beliefs,
        metrics=metrics,
    )

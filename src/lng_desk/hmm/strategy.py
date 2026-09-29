"""Trading rules mapping an HMM regime belief to a target position.

Each rule returns a target position in [-L, L] where +1 = fully long, -1 =
fully short. The backtest harness applies these one step at a time on the
filtered belief, never peeking at the realized return for that day.
"""
from __future__ import annotations

import numpy as np

from lng_desk.hmm.model import BEAR, BULL


def threshold_position(next_state_prob: np.ndarray, tau: float = 0.55) -> float:
    """Go long if P(bull) > tau, short if P(bear) > tau, else flat.

    Robust and easy to tune. `next_state_prob` is P(s_{t+1} | r_{1:t}).
    """
    p_bull = float(next_state_prob[BULL])
    p_bear = float(next_state_prob[BEAR])
    if p_bull > tau:
        return 1.0
    if p_bear > tau:
        return -1.0
    return 0.0


def kelly_position(
    exp_return: float,
    exp_var: float,
    risk_aversion: float = 3.0,
    leverage_cap: float = 1.0,
) -> float:
    """Kelly / mean-variance optimal fraction, clipped to +/- leverage_cap.

        f* = E[r] / (lambda * Var[r])

    This is where most of the model's real value lives: it sizes DOWN in the
    high-variance bear regime even when the directional call is uncertain.
    """
    if exp_var <= 0:
        return 0.0
    raw = exp_return / (risk_aversion * exp_var)
    return float(np.clip(raw, -leverage_cap, leverage_cap))


def tanh_position(exp_return: float, scale: float = 1e-3) -> float:
    """Smooth continuous mapping of expected return to [-1, 1].

    `scale` sets the return level (in the same units as r, e.g. daily decimal
    return) at which the position reaches ~tanh(1)=0.76 of full size.
    """
    return float(np.tanh(exp_return / scale))


def apply_no_trade_band(
    target: float, current: float, band: float = 0.05
) -> float:
    """Suppress churn: keep the current position unless the target moves by more
    than `band`. `band` should be set so a rebalance only fires when the
    expected edge exceeds the round-trip transaction cost in position units.
    """
    if abs(target - current) < band:
        return current
    return target

"""Gaussian Hidden Markov Model for regime detection on daily returns.

Three latent states (bear / neutral / bull) with Gaussian emissions, fit by
Baum-Welch (EM) in log-space. Online filtering produces a regime belief that
drives a position-sizing rule.

See model.py for the math, strategy.py for trading rules, backtest.py for the
walk-forward harness.
"""
from lng_desk.hmm.model import HiddenMarkovModel, HMMParams, BEAR, NEUTRAL, BULL
from lng_desk.hmm.strategy import (
    kelly_position, threshold_position, tanh_position, apply_no_trade_band,
)
from lng_desk.hmm.backtest import walk_forward_backtest, BacktestResult

__all__ = [
    "HiddenMarkovModel", "HMMParams", "BEAR", "NEUTRAL", "BULL",
    "kelly_position", "threshold_position", "tanh_position", "apply_no_trade_band",
    "walk_forward_backtest", "BacktestResult",
]

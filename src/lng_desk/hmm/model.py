"""Gaussian HMM with Baum-Welch fitting, log-space throughout.

Model
-----
Hidden state s_t in {0=bear, 1=neutral, 2=bull}. Observed scalar return r_t.
    r_t | s_t = k  ~  Normal(mu_k, sigma_k^2)
Parameters: pi (initial dist), A (transition matrix), mu (3,), sigma2 (3,).

Identification
--------------
EM is invariant to relabeling of states. After fitting we sort states by mu
ascending, so index 0 is always the lowest-mean (bear) regime and index 2 the
highest-mean (bull). Optionally a hard constraint pins mu_neutral = 0 and
enforces mu_bear <= 0 <= mu_bull in each M-step.

Numerics
--------
All recursions run in log-space with log-sum-exp to avoid underflow over long
return series. Variance is floored to avoid the classic EM collapse onto a
single observation (delta-spike likelihood -> +inf).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

BEAR, NEUTRAL, BULL = 0, 1, 2
_LOG_2PI = np.log(2.0 * np.pi)


def _logsumexp(a: np.ndarray, axis: int | None = None) -> np.ndarray:
    if axis is None:
        a_max = np.max(a)
        if not np.isfinite(a_max):
            a_max = 0.0
        return float(np.log(np.sum(np.exp(a - a_max))) + a_max)
    a_max = np.max(a, axis=axis, keepdims=True)
    a_max = np.where(np.isfinite(a_max), a_max, 0.0)
    out = np.log(np.sum(np.exp(a - a_max), axis=axis, keepdims=True)) + a_max
    return np.squeeze(out, axis=axis)


def _gaussian_logpdf(r: np.ndarray, mu: np.ndarray, sigma2: np.ndarray) -> np.ndarray:
    """Return log N(r_t; mu_k, sigma2_k) as a (T, K) matrix."""
    r = r[:, None]                      # (T, 1)
    mu = mu[None, :]                    # (1, K)
    sigma2 = sigma2[None, :]            # (1, K)
    return -0.5 * (_LOG_2PI + np.log(sigma2) + (r - mu) ** 2 / sigma2)


@dataclass
class HMMParams:
    pi: np.ndarray         # (K,)
    A: np.ndarray          # (K, K), row-stochastic
    mu: np.ndarray         # (K,)
    sigma2: np.ndarray     # (K,)

    @property
    def K(self) -> int:
        return self.mu.shape[0]

    def copy(self) -> "HMMParams":
        return HMMParams(self.pi.copy(), self.A.copy(), self.mu.copy(), self.sigma2.copy())


class HiddenMarkovModel:
    """Three-state Gaussian HMM. Fit with `.fit`, filter online with `.filter`."""

    def __init__(
        self,
        n_states: int = 3,
        var_floor: float = 1e-8,
        max_iter: int = 200,
        tol: float = 1e-6,
        n_restarts: int = 8,
        pin_neutral_zero: bool = False,
        enforce_sign: bool = False,
        random_state: int | None = 0,
    ):
        self.n_states = n_states
        self.var_floor = var_floor
        self.max_iter = max_iter
        self.tol = tol
        self.n_restarts = n_restarts
        self.pin_neutral_zero = pin_neutral_zero      # force mu_neutral = 0
        self.enforce_sign = enforce_sign              # clip mu_bear<=0<=mu_bull
        self.random_state = random_state
        self.params_: HMMParams | None = None
        self.log_likelihood_: float | None = None
        self.history_: list[float] = []

    # ------------------------------------------------------------------ fit
    def fit(self, r: np.ndarray) -> "HiddenMarkovModel":
        r = np.asarray(r, dtype=float).ravel()
        if r.size < 10 * self.n_states:
            raise ValueError(f"Need >= {10*self.n_states} observations, got {r.size}")

        rng = np.random.default_rng(self.random_state)
        best_ll = -np.inf
        best_params: HMMParams | None = None
        best_hist: list[float] = []

        for _ in range(self.n_restarts):
            params = self._init_params(r, rng)
            params, ll, hist = self._em(r, params)
            if ll > best_ll:
                best_ll, best_params, best_hist = ll, params, hist

        assert best_params is not None
        self.params_ = self._sort_by_mu(best_params)
        self.log_likelihood_ = best_ll
        self.history_ = best_hist
        return self

    def _init_params(self, r: np.ndarray, rng: np.random.Generator) -> HMMParams:
        K = self.n_states
        # Spread initial means across return quantiles so restarts explore modes.
        qs = np.linspace(0.15, 0.85, K)
        mu = np.quantile(r, qs) + rng.normal(0, r.std() * 0.1, size=K)
        if self.pin_neutral_zero and K == 3:
            mu[NEUTRAL] = 0.0
        sigma2 = np.full(K, r.var()) * rng.uniform(0.5, 1.5, size=K)
        sigma2 = np.maximum(sigma2, self.var_floor)
        # Sticky transition prior: regimes persist.
        A = np.full((K, K), 0.1 / (K - 1))
        np.fill_diagonal(A, 0.9)
        pi = np.full(K, 1.0 / K)
        return HMMParams(pi, A, mu, sigma2)

    def _em(self, r: np.ndarray, params: HMMParams) -> tuple[HMMParams, float, list[float]]:
        hist: list[float] = []
        prev_ll = -np.inf
        for _ in range(self.max_iter):
            log_alpha, log_beta, ll = self._forward_backward(r, params)
            gamma, xi_sum = self._expectations(r, params, log_alpha, log_beta, ll)
            params = self._m_step(r, gamma, xi_sum)
            hist.append(ll)
            if ll - prev_ll < self.tol and len(hist) > 1:
                break
            prev_ll = ll
        return params, ll, hist

    # --------------------------------------------------------- E-step pieces
    def _forward_backward(
        self, r: np.ndarray, p: HMMParams
    ) -> tuple[np.ndarray, np.ndarray, float]:
        T, K = r.size, p.K
        log_b = _gaussian_logpdf(r, p.mu, p.sigma2)        # (T, K)
        log_A = np.log(p.A + 1e-300)
        log_pi = np.log(p.pi + 1e-300)

        log_alpha = np.empty((T, K))
        log_alpha[0] = log_pi + log_b[0]
        for t in range(1, T):
            # logsumexp_j(alpha[t-1,j] + log_A[j,k]) for each k
            log_alpha[t] = log_b[t] + _logsumexp(
                log_alpha[t - 1][:, None] + log_A, axis=0
            )

        log_beta = np.zeros((T, K))
        for t in range(T - 2, -1, -1):
            log_beta[t] = _logsumexp(
                log_A + log_b[t + 1][None, :] + log_beta[t + 1][None, :], axis=1
            )

        ll = float(_logsumexp(log_alpha[-1]))
        return log_alpha, log_beta, ll

    def _expectations(
        self, r: np.ndarray, p: HMMParams,
        log_alpha: np.ndarray, log_beta: np.ndarray, ll: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        T, K = r.size, p.K
        log_gamma = log_alpha + log_beta - ll
        gamma = np.exp(log_gamma)                          # (T, K)

        log_b = _gaussian_logpdf(r, p.mu, p.sigma2)
        log_A = np.log(p.A + 1e-300)
        # xi_sum[i,j] = sum_t exp(alpha[t,i] + logA[i,j] + b[t+1,j] + beta[t+1,j] - ll)
        xi_sum = np.zeros((K, K))
        for t in range(T - 1):
            log_xi = (
                log_alpha[t][:, None]
                + log_A
                + log_b[t + 1][None, :]
                + log_beta[t + 1][None, :]
                - ll
            )
            xi_sum += np.exp(log_xi)
        return gamma, xi_sum

    def _m_step(self, r: np.ndarray, gamma: np.ndarray, xi_sum: np.ndarray) -> HMMParams:
        K = gamma.shape[1]
        pi = gamma[0] / gamma[0].sum()

        A = xi_sum / xi_sum.sum(axis=1, keepdims=True).clip(1e-300)

        Nk = gamma.sum(axis=0)                             # (K,)
        mu = (gamma * r[:, None]).sum(axis=0) / Nk.clip(1e-300)

        if self.pin_neutral_zero and K == 3:
            mu[NEUTRAL] = 0.0
        if self.enforce_sign and K == 3:
            # Soft projection: bear mean non-positive, bull mean non-negative.
            order = np.argsort(mu)
            mu[order[0]] = min(mu[order[0]], 0.0)
            mu[order[-1]] = max(mu[order[-1]], 0.0)

        diff2 = (r[:, None] - mu[None, :]) ** 2
        sigma2 = (gamma * diff2).sum(axis=0) / Nk.clip(1e-300)
        sigma2 = np.maximum(sigma2, self.var_floor)
        return HMMParams(pi, A, mu, sigma2)

    @staticmethod
    def _sort_by_mu(p: HMMParams) -> HMMParams:
        order = np.argsort(p.mu)                           # ascending -> bear..bull
        return HMMParams(
            pi=p.pi[order],
            A=p.A[np.ix_(order, order)],
            mu=p.mu[order],
            sigma2=p.sigma2[order],
        )

    # ------------------------------------------------------------- inference
    def filter(self, r: np.ndarray) -> np.ndarray:
        """Online filtered state probabilities P(s_t | r_{1:t}), shape (T, K)."""
        self._check_fitted()
        r = np.asarray(r, dtype=float).ravel()
        p = self.params_
        T, K = r.size, p.K
        log_b = _gaussian_logpdf(r, p.mu, p.sigma2)
        log_A = np.log(p.A + 1e-300)
        log_pi = np.log(p.pi + 1e-300)

        log_alpha = np.empty((T, K))
        log_alpha[0] = log_pi + log_b[0]
        for t in range(1, T):
            log_alpha[t] = log_b[t] + _logsumexp(log_alpha[t - 1][:, None] + log_A, axis=0)
        # normalize each row
        log_post = log_alpha - _logsumexp(log_alpha, axis=1)[:, None]
        return np.exp(log_post)

    def predict_next_state(self, belief: np.ndarray) -> np.ndarray:
        """Given P(s_t | r_{1:t}), return P(s_{t+1} | r_{1:t}) = A^T belief."""
        self._check_fitted()
        return self.params_.A.T @ np.asarray(belief, dtype=float)

    def predict_return_moments(self, belief: np.ndarray) -> tuple[float, float]:
        """Predicted next-day E[r] and Var[r] given current filtered belief.

        E[r_{t+1}]   = sum_k P(s_{t+1}=k) mu_k
        Var[r_{t+1}] = sum_k P(s_{t+1}=k) (sigma2_k + mu_k^2) - E[r]^2   (mixture var)
        """
        self._check_fitted()
        p = self.params_
        ns = self.predict_next_state(belief)               # (K,)
        mean = float(ns @ p.mu)
        second = float(ns @ (p.sigma2 + p.mu ** 2))
        var = max(second - mean ** 2, 0.0)
        return mean, var

    def viterbi(self, r: np.ndarray) -> np.ndarray:
        """Most-likely state path (hard decode) via log-space Viterbi."""
        self._check_fitted()
        r = np.asarray(r, dtype=float).ravel()
        p = self.params_
        T, K = r.size, p.K
        log_b = _gaussian_logpdf(r, p.mu, p.sigma2)
        log_A = np.log(p.A + 1e-300)
        log_pi = np.log(p.pi + 1e-300)

        delta = np.empty((T, K))
        psi = np.zeros((T, K), dtype=int)
        delta[0] = log_pi + log_b[0]
        for t in range(1, T):
            scores = delta[t - 1][:, None] + log_A         # (K_from, K_to)
            psi[t] = np.argmax(scores, axis=0)
            delta[t] = log_b[t] + np.max(scores, axis=0)
        path = np.empty(T, dtype=int)
        path[-1] = int(np.argmax(delta[-1]))
        for t in range(T - 2, -1, -1):
            path[t] = psi[t + 1, path[t + 1]]
        return path

    def _check_fitted(self) -> None:
        if self.params_ is None:
            raise RuntimeError("Model not fitted. Call .fit(returns) first.")

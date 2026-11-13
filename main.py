#!/usr/bin/env python3
"""Polymarket "Next CEO of NVIDIA?" forecaster (Python 3.13, stdlib only).

Jump-aware persistence + mean reversion, per market:

  q_tau(h) = clamp(centre(h) + z_tau * sigma * sqrt(h), 0, 1)

  * sigma: per-market volatility from RECENT 1-minute absolute changes.
    Prices sit flat most minutes then tick or jump, so the raw median
    absolute change is 0 for most markets and useless on its own. We use
    the mean absolute change over the last 480 minutes, winsorized at
    0.01 per minute so one huge jump (e.g. 0.35 -> 0.59 in a minute)
    cannot blow the spread up, converted to a per-sqrt-minute sigma
    with the normal factor 1.253 (E|N(0,s)| = s*sqrt(2/pi)), blended
    70/30 with the same estimate over the last 1440 minutes for
    stability, then floored at 0.0005 and capped at 0.02.
  * centre(h): the last price, pulled gently toward the market's median
    price over the last 480 minutes (mean reversion: a price that just
    jumped far from its recent median tends to drift back). The total
    pull is 25% of the gap, capped at +/-0.03, phased in linearly over
    the 240-minute horizon.
  * z_tau: heavy-tailed quantiles [-2.0, -0.70, 0, 0.70, 2.0] instead
    of the normal [-1.645, -0.674, 0, 0.674, 1.645], so the 5%/95%
    bands are ~22% wider than normal (jumps happen) while the
    25%/75% bands stay close to normal.
  * Markets with fewer than 10 prices fall back to the house baseline
    (sigma 0.0025, no drift). All quantiles are clamped to [0, 1],
    forced non-decreasing, and rounded to 6 decimals.

Reads every *.in file in the input directory (name order) and writes
one *.out file per case to the output directory. Input/output dirs come
from $MAKEFUN_INPUT_DIR / $MAKEFUN_OUTPUT_DIR, else /input / /output.
Deterministic: no randomness, no time, no network, sorted file order.
"""

import json
import math
import os
from pathlib import Path

INPUT_DIR = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
OUTPUT_DIR = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")

QUANTILES = [0.05, 0.25, 0.5, 0.75, 0.95]
# Heavy-tailed z-scores (see module docstring).
Z = [-2.0, -0.70, 0.0, 0.70, 2.0]

# Volatility estimator constants.
WIN_RECENT = 480        # minutes of recent history for sigma
WIN_LONG = 1440         # minutes of longer history blended in
WINSOR_CAP = 0.01       # cap on a single minute's |change|
MEAN_TO_SIGMA = 1.2533  # 1 / sqrt(2/pi): E|N(0,s)| = s * sqrt(2/pi)
SIGMA_FLOOR = 0.0005
SIGMA_CAP = 0.02
SIGMA_FALLBACK = 0.0025  # house baseline sigma, used when <10 prices
MIN_PRICES = 10

# Mean-reversion constants.
REVERT_WINDOW = 480     # minutes whose median price is the anchor
REVERT_WEIGHT = 0.25    # fraction of (median - last) pulled back
REVERT_CAP = 0.03       # max total pull in price units


def clamp6(x):
    """Clamp to [0, 1] and round to 6 decimals (0, never -0)."""
    v = round(min(1.0, max(0.0, x)) * 1e6) / 1e6
    return v + 0.0


def _median(sorted_vals):
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return sorted_vals[mid]
    return 0.5 * (sorted_vals[mid - 1] + sorted_vals[mid])


def _winsor_mean_abs_change(prices, window):
    """Mean |1-min change| over the last `window` minutes, each capped."""
    diffs = prices[-window - 1:] if len(prices) > window + 1 else prices
    if len(diffs) < 2:
        return 0.0
    total = 0.0
    count = 0
    for i in range(len(diffs) - 1):
        d = abs(diffs[i + 1] - diffs[i])
        if d > WINSOR_CAP:
            d = WINSOR_CAP
        total += d
        count += 1
    return total / count if count else 0.0


def estimate_sigma(prices):
    """Per-market per-sqrt-minute sigma from recent absolute changes."""
    recent = _winsor_mean_abs_change(prices, WIN_RECENT)
    long_ = _winsor_mean_abs_change(prices, WIN_LONG)
    mean_abs = 0.7 * recent + 0.3 * long_
    sigma = MEAN_TO_SIGMA * mean_abs
    if sigma < SIGMA_FLOOR:
        sigma = SIGMA_FLOOR
    elif sigma > SIGMA_CAP:
        sigma = SIGMA_CAP
    return sigma


def forecast_market(market, horizon):
    prices = market["prices"]
    if not prices:
        raise ValueError("market %s has no prices" % market["id"])
    x = prices[-1]
    if len(prices) < MIN_PRICES:
        sigma = SIGMA_FALLBACK
        pull = 0.0
    else:
        sigma = estimate_sigma(prices)
        anchor = _median(sorted(prices[-REVERT_WINDOW:]))
        pull = REVERT_WEIGHT * (anchor - x)
        if pull > REVERT_CAP:
            pull = REVERT_CAP
        elif pull < -REVERT_CAP:
            pull = -REVERT_CAP
    rows = []
    for h in range(1, horizon + 1):
        centre = x + pull * (h / horizon)
        spread = sigma * math.sqrt(h)
        row = [clamp6(centre + z * spread) for z in Z]
        # Enforce non-decreasing (clamping at 0/1 can only help, but be safe).
        for j in range(1, 5):
            if row[j] < row[j - 1]:
                row[j] = row[j - 1]
        rows.append(row)
    return rows


def main():
    in_dir = Path(INPUT_DIR)
    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    inputs = sorted(p for p in in_dir.iterdir() if p.name.endswith(".in"))
    for path in inputs:
        case_id = path.name[: -len(".in")]
        with open(path, "r", encoding="utf-8") as f:
            case = json.load(f)
        if list(case["quantiles"]) != QUANTILES:
            raise ValueError(
                "%s asks for quantiles %r, not %r"
                % (path.name, case["quantiles"], QUANTILES)
            )
        horizon = int(case["horizon_minutes"])
        forecasts = [
            {"id": m["id"], "q": forecast_market(m, horizon)}
            for m in case["markets"]
        ]
        out_path = out_dir / ("%s.out" % case_id)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"forecasts": forecasts}) + "\n")


if __name__ == "__main__":
    main()

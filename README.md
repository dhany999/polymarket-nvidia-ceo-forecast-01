# Polymarket "Next CEO of NVIDIA?" forecaster

Entry for make.fun competition `polymarket-nvidia-ceo-forecast-01`: forecast
every market's Yes price minute by minute, 240 minutes ahead, at quantiles
0.05 / 0.25 / 0.5 / 0.75 / 0.95. Python 3.13, standard library only, no
network, deterministic.

## Approach — jump-aware persistence + mean reversion

For each market, with `x` its last price and `h = 1..240`:

```
q_tau(h) = clamp(centre(h) + z_tau * sigma * sqrt(h), 0, 1)
```

- **sigma (per-market, recent):** prices sit flat most minutes then tick
  or jump, so the raw median absolute 1-minute change is 0 for most
  markets. Instead sigma comes from the mean absolute 1-minute change
  over the last 480 minutes, winsorized at 0.01 per minute (one huge
  jump cannot blow the spread up), converted with the normal factor
  1.2533, blended 70/30 with the same estimate over the last 1440
  minutes, floored at 0.0005 and capped at 0.02. Quiet markets get
  narrow bands, jumpy markets wide ones.
- **centre(h) (mean reversion):** the last price pulled 25% of the way
  toward the market's median price over the last 480 minutes (capped
  at ±0.03 total), phased in linearly over the horizon. A price that
  just jumped far from its recent median tends to drift back.
- **Heavy tails:** z = [-2.0, -0.70, 0, 0.70, 2.0] instead of the
  normal quantiles, so the 5%/95% bands are ~22% wider than normal.
- **Fallback:** markets with fewer than 10 prices use the house
  baseline (sigma 0.0025, no drift). All quantiles are clamped to
  [0, 1], forced non-decreasing, rounded to 6 decimals.

## Local practice score

Scored locally on practice cases p00–p04 (each scored against the next
case's realised prices, same 5 cases for both):

| forecaster | mean pinball loss |
|---|---|
| this entry | **0.3176** |
| house baseline (persistence, sigma 0.0025) | 0.3925 |

House baseline scores 0.363589 on all 6 practice cases as published;
p05 cannot be scored locally (no later case holds its answers). The
local comparison above is apples-to-apples on the 5 scoreable cases.

## Run

```sh
mkdir -p out && MAKEFUN_INPUT_DIR=<kit>/input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Runs in ~0.05 s per case locally (limit is 8 s), output < 1 MiB per case.

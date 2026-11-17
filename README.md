[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Indodegen/gta6-twitch-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Indodegen/gta6-twitch-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Built for the [make.fun bounty](https://make.fun/bounty/gta6-twitch-ccu-forecast-01) — Forecast GTA VI's launch-day Twitch viewers hour by hour.

# GTA VI launch-day Twitch viewers — hour-by-hour forecast

Entry for `gta6-twitch-ccu-forecast-01` (make.fun). `main.py` (Python 3.13,
standard library only, no network) reads one case file `/input/<id>.in` and
writes `/output/<id>.out`: for each of hours 2–24 of the release day, five
quantiles (5%, 25%, 50%, 75%, 95%) of Twitch's concurrent viewers in the
Grand Theft Auto VI category. Deterministic, ~0.1 s per case.

## Method

The forecast is fitted at run time from the case's own `comparables`
(past big launches' hourly Twitch curves):

1. **Filter.** Keep comparables with a complete 24-hour release-day curve
   and a genuine hour-1 print (≥ 10,000 viewers). Games whose hour 1 was
   still pre-unlock (a few hundred viewers) are excluded — their ratios
   explode to 100–2000× and would poison the fit.
2. **Regress, per hour.** For each hour h = 2..24, regress the log-ratio
   `ln(y_h / y_1)` on three features:
   - `ln(hour-1 print)` — the peak multiple shrinks as hour 1 grows
     (huge launches are already near their peak at hour 1);
   - `ln(viewers in the hour just before the release day)` — captures
     whether the category is still ramping from the New Zealand unlock;
   - a 1/0 dummy for "also launched on PC" (the target is console-only,
     so the case itself gets 0; PC simultaneous unlocks peak earlier).
3. **Quantiles.** Median = `p1 · exp(prediction)`; spread = the
   regression's residual standard deviation × 0.9, so
   `q_τ = p1 · exp(pred + z_τ · sd)`. Features are clamped to the range
   seen in the comparables, so a record-size launch cannot extrapolate
   wildly.
4. **Fallbacks.** Fewer than 8 usable comparables → median log-ratio
   curve; none at all (or any error) → flat persistence forecast.
   The program never crashes and never emits an invalid case.

## Local practice scores

Answers for the four practice cases (hourly counts, hours 2–24) were
taken from SullyGnome's public hourly averages, the same source the kit
names in `input/NOTICE.txt`; hour-1 values match the kit's `known`
prints exactly. Mean pinball loss on the log scale:

| case | game | loss | typical miss | 90% coverage |
|------|------|------|--------------|--------------|
| p00 | Marvel's Wolverine | 0.2675 | 54.9% | 0.70 |
| p01 | Red Dead Redemption 2 | 0.1782 | 36.0% | 0.96 |
| p02 | God of War Ragnarök | 0.1304 | 22.9% | 1.00 |
| p03 | Marvel's Spider-Man 2 | 0.1675 | 31.1% | 0.91 |
| **mean** | | **0.1859** | | **0.89** |

House persistence baseline on the same practice: **0.387** (typical miss
82.8%, coverage 0.783). This entry beats it by ~52%.

Checks: two runs produce byte-identical outputs; single-case run
~0.1 s (limit 8 s); edge cases (tiny/huge/zero hour-1 print, empty
history, no comparables) all yield valid output files.

## Run locally

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=<kit>/input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

## Files

- `main.py` — the entry (the only code file)
- `README.md` — this file
- `LICENSE` — MIT

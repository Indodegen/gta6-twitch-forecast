"""Forecast GTA VI launch-day Twitch viewers, hour by hour (quantiles).

Method (fitted at run time from the case's own comparables, no network):
  For every comparable past launch with a complete release-day curve and a
  genuine hour-1 print (>= 10k viewers), take the log-ratio of each later
  hour to hour 1.  Regress that log-ratio, separately per hour, on
    * log(hour-1 print),
    * log(viewers in the hour just before the release day), and
    * a 1/0 dummy for "the comparable also launched on PC"
  (the target game is console-only, so the dummy is 0 for the case).
  The fitted value is the log of the forecast median ratio; the spread is
  the regression's residual standard deviation (x0.9), so each quantile is
  p1 * exp(pred + z_tau * sd).  Features are clamped to the range seen in
  the comparables, so a record-size launch cannot extrapolate wildly.

  Why these features: hour 1 (00:00 UTC) catches only the time zones that
  have unlocked so far, so the later US-evening peak is a multiple of it;
  that multiple shrinks as the hour-1 print grows (big launches are
  already near their peak at hour 1), and the hour before the day starts
  captures whether the category is still ramping up from the New Zealand
  unlock.  On the four practice launches this scores a mean pinball loss
  of ~0.186 (house persistence baseline ~0.387).

  Fallbacks (never crash, never emit an invalid case): if too few usable
  comparables remain, use the median log-ratio curve with its spread; if
  even that is impossible, fall back to a flat persistence forecast.
  Standard library only; deterministic; runs in well under a second.
"""

import json
import math
import os
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.6448536269514722, -0.6744897501960817, 0.0,
     0.6744897501960817, 1.6448536269514722]

MIN_P1 = 10000          # a comparable needs a real launch hour-1 print
MIN_COMPARABLES = 8      # below this, fall back to the median-ratio curve
SD_MULT = 0.9            # shrink residual spread slightly (practice-optimal)
SD_FLOOR = 0.10
SD_CAP = 0.90
BASE_SIGMA = 0.15        # persistence fallback spread, per sqrt hour


def _parse_time(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _log(value):
    return math.log(max(1.0, float(value)))


def _round2(value):
    """Round to 2 decimals, half up, returning an int for whole numbers."""
    scaled = value * 100.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    out = whole / 100.0
    return int(out) if out.is_integer() else out


def _clean_quantiles(raw):
    """Clamp to (0, 1e9], force non-decreasing, round to 2 decimals."""
    out = []
    prev = 0.01
    for value in raw:
        if not math.isfinite(value) or value <= 0:
            value = prev
        value = min(value, 1e9)
        value = max(value, prev)
        value = _round2(value)
        value = max(value, prev)
        out.append(value)
        prev = value
    return out


def _ols(features, target):
    """Least squares with intercept for a small design matrix.

    Returns (coefficients including intercept, residual population sd).
    Solved by Gaussian elimination on the normal equations with a tiny
    ridge term for stability; deterministic.
    """
    n = len(target)
    width = len(features[0]) + 1
    rows = [[1.0] + list(row) for row in features]
    normal = [[sum(rows[i][a] * rows[i][b] for i in range(n))
               for b in range(width)] for a in range(width)]
    rhs = [sum(rows[i][a] * target[i] for i in range(n))
           for a in range(width)]
    for a in range(1, width):
        normal[a][a] += 1e-9
    for col in range(width):
        pivot = max(range(col, width), key=lambda r: abs(normal[r][col]))
        normal[col], normal[pivot] = normal[pivot], normal[col]
        rhs[col], rhs[pivot] = rhs[pivot], rhs[col]
        if abs(normal[col][col]) < 1e-12:
            continue
        for r in range(width):
            if r != col and normal[r][col] != 0.0:
                factor = normal[r][col] / normal[col][col]
                for cc in range(col, width):
                    normal[r][cc] -= factor * normal[col][cc]
                rhs[r] -= factor * rhs[col]
    coef = [rhs[i] / normal[i][i] if abs(normal[i][i]) > 1e-12 else 0.0
            for i in range(width)]
    resid = [target[i] - sum(coef[j] * rows[i][j] for j in range(width))
             for i in range(n)]
    sd = statistics.pstdev(resid) if n > 1 else 0.3
    return coef, sd


def _release_day(comp):
    """The comparable's 24 hourly viewer counts for its release day."""
    day = _parse_time(comp["day_start"])
    by_hour = {}
    for row in comp.get("hourly") or []:
        try:
            by_hour[_parse_time(row["from"])] = row
        except (KeyError, ValueError):
            continue
    curve = []
    for h in range(24):
        row = by_hour.get(day + timedelta(hours=h))
        if row is None or row.get("viewers") is None:
            return None
        value = float(row["viewers"])
        if value <= 0:
            return None
        curve.append(value)
    return curve, by_hour, day


def _usable_comparables(case):
    """Filtered comparables with everything the regression needs."""
    usable = []
    for comp in case.get("comparables") or []:
        parsed = _release_day(comp)
        if parsed is None:
            continue
        curve, by_hour, day = parsed
        if curve[0] < MIN_P1:
            continue
        prelast = None
        for back in range(1, 25):
            row = by_hour.get(day - timedelta(hours=back))
            if row is not None and row.get("viewers"):
                prelast = float(row["viewers"])
                break
        if prelast is None:
            prelast = curve[0]
        usable.append({
            "curve": curve,
            "p1": curve[0],
            "prelast": prelast,
            "pc": "PC" in (comp.get("platforms") or ""),
        })
    return usable


def _case_features(case):
    """Hour-1 print and the pre-day level for the case itself."""
    p1 = 1.0
    known = case.get("known") or []
    for row in known:
        if row.get("hour") == 1 and row.get("viewers"):
            p1 = max(1.0, float(row["viewers"]))
            break
    day = _parse_time(case["day_start"])
    by_hour = {}
    for row in case.get("history_hourly") or []:
        try:
            by_hour[_parse_time(row["from"])] = row
        except (KeyError, ValueError):
            continue
    prelast = None
    for back in range(1, 25):
        row = by_hour.get(day - timedelta(hours=back))
        if row is not None and row.get("viewers"):
            prelast = float(row["viewers"])
            break
    if prelast is None:
        prelast = p1
    return p1, prelast


def _persistence(p1):
    return {h: [p1 * math.exp(z * BASE_SIGMA * math.sqrt(h - 1))
                for z in Z] for h in range(2, 25)}


def _median_curve(comps, p1):
    """Median log-ratio curve with per-hour spread (fallback model)."""
    out = {}
    for h in range(2, 25):
        ratios = sorted(math.log(c["curve"][h - 1] / c["p1"]) for c in comps)
        mid = ratios[len(ratios) // 2]
        sd = statistics.pstdev(ratios) if len(ratios) > 1 else 0.3
        sd = min(max(sd * SD_MULT, SD_FLOOR), SD_CAP)
        out[h] = [p1 * math.exp(mid + z * sd) for z in Z]
    return out


def _regression_forecast(comps, p1, prelast):
    """Per-hour OLS forecast; see the module docstring for the model."""
    train_x = [[_log(c["p1"]), _log(c["prelast"]),
                1.0 if c["pc"] else 0.0] for c in comps]
    n_train = len(train_x)
    means = [sum(row[j] for row in train_x) / n_train for j in range(2)]
    means.append(0.0)  # the PC dummy is not centred
    lows = [min(row[j] for row in train_x) - means[j] for j in range(2)]
    highs = [max(row[j] for row in train_x) - means[j] for j in range(2)]
    centred = [[row[j] - means[j] for j in range(3)] for row in train_x]
    case_x = [_log(p1) - means[0], _log(prelast) - means[1], 0.0]
    case_x[0] = min(max(case_x[0], lows[0]), highs[0])
    case_x[1] = min(max(case_x[1], lows[1]), highs[1])
    out = {}
    for h in range(2, 25):
        target = [math.log(c["curve"][h - 1] / c["p1"]) for c in comps]
        coef, sd = _ols(centred, target)
        pred = coef[0] + sum(coef[j + 1] * case_x[j] for j in range(3))
        sd = min(max(sd * SD_MULT, SD_FLOOR), SD_CAP)
        out[h] = [p1 * math.exp(pred + z * sd) for z in Z]
    return out


def forecast_case(case):
    p1, prelast = _case_features(case)
    try:
        comps = _usable_comparables(case)
        if len(comps) >= MIN_COMPARABLES:
            raw = _regression_forecast(comps, p1, prelast)
        elif comps:
            raw = _median_curve(comps, p1)
        else:
            raw = _persistence(p1)
    except Exception:
        raw = _persistence(p1)
    hours = []
    for row in case["forecast"]:
        h = int(row["hour"])
        hours.append({"hour": h, "q": _clean_quantiles(raw[h])})
    hours.sort(key=lambda r: r["hour"])
    return {"hours": hours}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n",
            encoding="utf-8")


if __name__ == "__main__":
    main()

"""Pure transforms on a series: dict {period: value}. Periods are '1990:Q1' or '1990'."""
import math

DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def log_base(s: dict, base: float = math.e) -> dict:
    """Logarithm in any base (math.e for natural, 60 for sexagesimal, 2, 10...). Non-positive values are dropped."""
    d = math.log(base)
    return {p: math.log(v) / d for p, v in s.items() if v > 0}


def _year(p: str) -> str:
    return p.split(":")[0]


def ratio(num: dict, den: dict, scale: float = 1.0) -> dict:
    """num/den * scale. If den is annual ('1990') it is matched to every quarter of that year."""
    out = {}
    for p, v in num.items():
        d = den.get(p, den.get(_year(p)))
        if d:
            out[p] = v / d * scale
    return out


def growth(s: dict, lag: int = 4) -> dict:
    """Log growth over `lag` observations (4 = year-on-year for quarterly data); in natural-log units."""
    ps = sorted(s)
    return {ps[i]: math.log(s[ps[i]] / s[ps[i - lag]]) for i in range(lag, len(ps)) if s[ps[i]] > 0 and s[ps[i - lag]] > 0}


def index_to(s: dict, base_period: str, base_value: float = 100.0) -> dict:
    b = s[base_period]
    return {p: v / b * base_value for p, v in s.items()}


def to_base(x: float, base: int = 60, places: int = 3) -> str:
    """Positional representation of x in `base`, e.g. 3725.5 -> '1;2,5.30' style: groups joined by ',' (base>36 uses numeric groups)."""
    sign, x = ("-" if x < 0 else ""), abs(x)
    whole, frac = int(x), x - int(x)
    groups = []
    while True:
        whole, r = divmod(whole, base)
        groups.append(r)
        if not whole:
            break
    head = ",".join(str(g) for g in reversed(groups)) if base > 36 else "".join(DIGITS[g] for g in reversed(groups))
    tail = []
    for _ in range(places):
        frac *= base
        d = int(frac)
        tail.append(d)
        frac -= d
    sep = "," if base > 36 else ""
    return f"{sign}{head};{sep.join(str(t) if base > 36 else DIGITS[t] for t in tail)}"


def ols_slope(s: dict, start: str, end: str) -> float | None:
    """Least-squares slope of value against observation index between two periods (inclusive)."""
    ps = [p for p in sorted(s) if start <= p <= end]
    n = len(ps)
    if n < 3:
        return None
    xs, ys = range(n), [s[p] for p in ps]
    mx, my = (n - 1) / 2, sum(ys) / n
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)


def rolling_sum(s: dict, n: int = 4) -> dict:
    """Sum of the last n observations (4 turns a quarterly flow into a trailing-year flow)."""
    ps = sorted(s)
    return {ps[i]: sum(s[q] for q in ps[i - n + 1:i + 1]) for i in range(n - 1, len(ps))}


def pct_change(s: dict, lag: int = 1) -> dict:
    """Percent change over `lag` observations (4 on quarterly data = year-on-year)."""
    ps = sorted(s)
    return {ps[i]: (s[ps[i]] / s[ps[i - lag]] - 1) * 100 for i in range(lag, len(ps)) if s[ps[i - lag]]}

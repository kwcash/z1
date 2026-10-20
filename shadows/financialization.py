"""Has finance grown faster than the economy it serves? Fed series only, no outside data."""

GDP = "FU086902005.Q"            # GDP, quarterly flow
FIN_ASSETS = "FL794090005.Q"     # domestic financial sectors, total financial assets
HH_LIAB = "FL154190005.Q"        # households, total liabilities
HH_NW = "FL152090005.Q"          # households, net worth
NFC_FIN = "FL104090005.Q"        # nonfinancial corporations, total financial assets


def run(ctx):
    t = ctx.t
    gdp_year = ctx.put("GDP_4Q", t.rolling_sum(ctx.fed(GDP), 4), "GDP, trailing 4 quarters", f"rolling_sum({GDP},4)", "Millions of dollars", [GDP])
    fin, hhl, hhnw, nfc = (ctx.fed(s) for s in (FIN_ASSETS, HH_LIAB, HH_NW, NFC_FIN))

    ratios = {
        "FIN_ASSETS_TO_GDP": (fin, FIN_ASSETS, "Financial-sector assets / GDP"),
        "HH_DEBT_TO_GDP": (hhl, HH_LIAB, "Household liabilities / GDP"),
        "HH_NETWORTH_TO_GDP": (hhnw, HH_NW, "Household net worth / GDP"),
        "NFC_FINASSETS_TO_GDP": (nfc, NFC_FIN, "Nonfinancial corporate financial assets / GDP"),
    }
    out = {}
    for sid, (num, src, label) in ratios.items():
        out[sid] = ctx.put(sid, t.ratio(num, gdp_year), label, f"{src} / GDP_4Q", "ratio", [src, GDP])
        # same series on the log scales: natural, and base 60 (one unit = a 60-fold change)
        ctx.put(sid + "_LN", t.log_base(out[sid]), label + " (ln)", f"ln({sid})", "ln units", [src, GDP])
        l60 = ctx.put(sid + "_LOG60", t.log_base(out[sid], 60), label + " (log base 60)", f"log60({sid})", "log60 units", [src, GDP])
        ctx.put(sid + "_B60", {p: v for p, v in out[sid].items()}, label + " (base-60 digits)", f"to_base({sid},60)", "ratio",
                [src, GDP], text={p: t.to_base(v, 60) for p, v in out[sid].items()})

    exp = "E1_FINANCE_VS_ECONOMY"
    ctx.experiment(exp, "Financial-sector assets have grown faster than GDP since the postwar era, and the gap widened after a break year.",
                   "OLS slope of ln(financial assets / GDP) per quarter over successive windows; positive = finance outgrowing the economy.")
    ln = ctx.t.log_base(out["FIN_ASSETS_TO_GDP"])
    for a, b in [("1946:Q4", "1969:Q4"), ("1970:Q1", "1979:Q4"), ("1980:Q1", "1999:Q4"), ("2000:Q1", "2007:Q4"), ("2008:Q1", "2026:Q2")]:
        ctx.result(exp, f"ln_slope_per_qtr {a}..{b}", t.ols_slope(ln, a, b), "financial assets/GDP")
    ctx.result(exp, "ratio_first", out["FIN_ASSETS_TO_GDP"][min(out["FIN_ASSETS_TO_GDP"])])
    ctx.result(exp, "ratio_last", out["FIN_ASSETS_TO_GDP"][max(out["FIN_ASSETS_TO_GDP"])])
